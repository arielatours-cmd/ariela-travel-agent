import json
import os
from datetime import date

from flask import Blueprint, jsonify, request

from travel_agents import (
    _member_context, _persist_gender, _normalize_services,
    _travel_matches, _flight_handoff, _load_json,
    _LODGING_SCHEMA_FILE, _CAR_SCHEMA_FILE, _openai_json, _conversation,
)
from lodging_providers import lodging_inventory_status

ariella_chat_v2 = Blueprint("ariella_chat_v2", __name__)
ENGINE_VERSION = "contextual-chat-v15"

SYSTEM = """את מפעילה שתי שכבות באותה קריאה ובסדר מחייב:
1. טינקרבל השקטה מבינה קודם את ההודעה האחרונה בתוך כל ההקשר ומעדכנת profile_patch.
2. רק אחרי שהבנת מה נאמר, אריאלה מנסחת reply טבעי על סמך ההודעה, ההיסטוריה, הפרופיל הקיים וה-profile_patch שזה עתה חילצת.

אריאלה היא סוכנת נסיעות אישית שמדברת כמו ChatGPT בשיחה חופשית, לא כמו שאלון. הגיבי למה שהאדם אמר עכשיו. אם הוא שואל — עני. אם הוא מתלבט — חשבי איתו. אם הוא מוסר מידע — הכירי בו והמשיכי ממנו. אם הוא מתקן — קבלי את התיקון והמשיכי.

חוק קשיח: אסור לשאול על פרט שכבר מופיע בפרופיל הקיים, בהיסטוריה, בהודעה האחרונה או ב-profile_patch של התור הנוכחי. אל תשאלי רשימת שאלות ואל תנסי להשלים טופס. מותר לכל היותר סימן שאלה אחד ב-reply, ורק לשאלת המשך אחת טבעית. לעולם אל תבקשי יחד יעד, תאריך ונוסעים. לעולם אל תגידי "ספרי לי קצת על החופשה" או נוסח דומה. אל תזכירי נתב״ג או חיפוש טיסות עד שזה רלוונטי ממש.

דוגמה מחייבת: אם ההודעה היא "בא לי לטוס עם הבת שלי", טינקרבל מחלצת קודם adults=1, children=1, travel_party_type=family. לכן אריאלה כבר יודעת מי נוסע ואסור לה לשאול "מי נוסע", "מי נוסע איתך" או לצרף את זה לרשימת פרטים. תשובה טבעית אפשרית היא בסגנון "איזה כיף 😊 יש לכן כבר כיוון בראש או שאת רוצה שנחשוב יחד?" — זו דוגמה לסגנון, לא טקסט קבוע.

טינקרבל אינה מדברת עם הלקוח ואינה קובעת את השאלה הבאה. תיקון חדש גובר על מידע ישן. אל תנחשי עובדות שלא נאמרו. "עם הבת שלי"/"אני והבת שלי" => adults=1, children=1, travel_party_type=family כשאין מידע אחר שסותר; "עם הבן שלי" מקביל; "עם בעלי"/"עם אשתי" => adults=2.

נרמול פנימי בלבד: vacation_type יכול להיות business / ski / standard. services כולל flight כשמדובר בטיסה. שדות אפשריים: vacation_type, services, destination_mode, destinations, departure_airports, date_mode, departure_date, return_date, outbound_month, return_month, date_flex_days, adults, children, child_ages, infants, travel_party_type, budget_mode, budget_amount, flight_preference, baggage, vacation_styles, lodging_type, rooms, bathrooms, hotel_rooms, lodging_budget_mode, lodging_budget_amount, pickup_location, dropoff_location, driver_age, car_type, transmission, car_budget_mode, car_budget_amount, car_features, notes.

חשוב: סדר המפתחות בפלט הוא חלק מהתהליך — קודם חלצי profile_patch ורק אחר כך כתבי reply.
החזירי JSON בלבד ובקיצור, בדיוק במבנה:
{"profile_patch":{},"reply":"תשובת אריאלה הטבעית","intent":"conversation","unclear":[]}
"""


def _clean_patch(value):
    if not isinstance(value, dict):
        return {}
    return {k: v for k, v in value.items() if v is not None}


def _has_destination(p):
    return bool(p.get("destinations")) or p.get("destination_mode") in {"open", "ariella", "flexible"}


def _has_dates(p):
    return bool((p.get("departure_date") and p.get("return_date")) or p.get("outbound_month"))


def _has_travelers(p):
    try:
        return int(p.get("adults") or 0) > 0
    except (TypeError, ValueError):
        return False


def _has_budget(p):
    return bool(p.get("budget_mode") or p.get("budget_amount") not in (None, ""))


def _stage(p):
    if not p.get("vacation_type"):
        return "purpose"
    if not _has_destination(p):
        return "destination"
    if not _has_dates(p):
        return "dates"
    if not _has_travelers(p):
        return "travelers"
    if not p.get("flight_preference") or not p.get("baggage"):
        return "flight_preferences"
    if not _has_budget(p):
        return "budget"
    return "confirm"


def _single_pass(message, history, profile):
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    model = os.getenv("ARIELLA_MODEL", "gpt-5.6-luna").strip()
    context = {"current_date": date.today().isoformat(), "known_trip_context": profile}
    result = _openai_json(
        key, model,
        SYSTEM + "\nהקשר פנימי שכבר ידוע; אל תחזרי עליו סתם:\n" + json.dumps(context, ensure_ascii=False),
        _conversation((history or [])[-6:], message),
        max_output_tokens=280,
    )
    if not isinstance(result, dict):
        result = {}
    result["profile_patch"] = _clean_patch(result.get("profile_patch"))
    if not isinstance(result.get("unclear"), list):
        result["unclear"] = []
    return result


def _safe_reply(result):
    reply = str(result.get("reply") or "").strip()
    return reply or "ספרי לי עוד 😊"


@ariella_chat_v2.post("/api/ariella/chat")
def ariella_chat():
    body = request.get_json(silent=True) or {}
    message = str(body.get("message") or "").strip()
    if not message:
        return jsonify({"status": "error", "message": "message is required"}), 400

    profile = dict(body.get("profile") if isinstance(body.get("profile"), dict) else {})
    history = body.get("history") if isinstance(body.get("history"), list) else []

    if "known_companions" not in profile or "member_context_loaded" not in profile:
        member = _member_context()
        if member:
            if member.get("gender") and not profile.get("customer_gender"):
                profile["customer_gender"] = member.get("gender")
            profile["known_companions"] = member.get("companions") or []
            if profile.get("customer_gender"):
                _persist_gender(member["id"], profile.get("customer_gender"))
        else:
            profile.setdefault("known_companions", [])
        profile["member_context_loaded"] = True

    if not profile.get("departure_airports"):
        profile["departure_airports"] = ["TLV"]

    try:
        result = _single_pass(message, history, profile)
    except Exception as exc:
        return jsonify({"status": "error", "message": "אריאלה לא זמינה כרגע.", "detail": str(exc), "engine_version": ENGINE_VERSION}), 503

    merged = dict(profile)
    merged.update(result.get("profile_patch") or {})
    merged["services"] = _normalize_services(merged.get("services"))
    if merged.get("vacation_type"):
        if not merged["services"]:
            merged["services"] = ["flight"]
        elif "flight" not in merged["services"]:
            merged["services"].insert(0, "flight")

    stage = _stage(merged)
    complete = stage == "confirm"
    services = merged.get("services") or []
    reply = _safe_reply(result)

    travel = _travel_matches(merged) if complete and ("attractions" in services or "route" in services) else []
    lodging_status = lodging_inventory_status() if complete and "lodging" in services else {"providers": [], "live_provider_count": 0, "live_inventory_available": False}
    return jsonify({
        "status": "success", "agent": "Ariella", "engine_version": ENGINE_VERSION,
        "reply": reply, "profile": merged, "intent": result.get("intent") or "conversation",
        "missing_question": "", "stage": stage, "show_purpose_picker": False,
        "show_service_picker": False, "ui_choice": None, "services": services,
        "ready_for_flights": complete and "flight" in services, "flight_search_started": False,
        "ready_for_lodging": complete and "lodging" in services,
        "ready_for_car": complete and "car" in services, "ready_for_travel": bool(travel),
        "intake_complete": complete, "requires_confirmation": complete,
        "confirmation_text": "עברו על כל הפרטים ב'החופשה שלי'. אם הכול נכון, אשרו יציאה לחיפוש.",
        "tinkerbell_handoff": _flight_handoff(merged), "travel_agent": {"attractions": travel},
        "lodging_schema": _load_json(_LODGING_SCHEMA_FILE, {}) if complete and "lodging" in services else {},
        "car_schema": _load_json(_CAR_SCHEMA_FILE, {}) if complete and "car" in services else {},
        "inventory_status": {"lodging": lodging_status, "car": "provider_pending"},
    })
