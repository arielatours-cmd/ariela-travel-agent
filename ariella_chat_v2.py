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
ENGINE_VERSION = "contextual-chat-v14"

SYSTEM = """את אריאלה, סוכנת נסיעות אישית. דברי עם האדם בדיוק כשיחה טבעית ב-ChatGPT, לא כשאלון.

הדבר החשוב ביותר: הגיבי למה שהאדם אמר עכשיו בתוך ההקשר של השיחה. אל תנסי להשלים טופס בכל תשובה. אם הוא שואל שאלה — עני עליה. אם הוא מתלבט — חשבי איתו. אם הוא מספר משהו — התייחסי אליו. אם הוא משנה את דעתו — המשיכי מהשינוי.

אסור לשאול שוב פרט שכבר נאמר. מותר לכל היותר לשאול שאלה אחת בסוף, ורק אם היא המשך טבעי של השיחה. לעולם אל תבקשי יחד יעד, תאריך ונוסעים. לעולם אל תגידי "ספרי לי קצת על החופשה" ולא תציגי רשימת פרטים שחסרים. אל תזכירי נתב״ג או חיפוש טיסות עד שהשיחה באמת מגיעה לחיפוש.

חשוב במיוחד: אם ההודעה האחרונה עצמה כבר מכילה תשובה לשאלה קודמת, קודם הכירי בתשובה והמשיכי ממנה. לדוגמה, "בא לי לטוס עם הבת שלי" כבר אומר שמדובר במשתמשת ובבת שלה. אסור לענות כאילו לא נמסר מידע ואסור לשאול שוב מי נוסע. אין צורך לדעת מיד את גיל הבת; גיל אפשר לברר מאוחר יותר רק כשזה באמת נדרש.

במקביל לתשובה, פעלי גם כטינקרבל השקטה: חלצי מן המשמעות של השיחה עובדות חדשות ותיקונים ל-profile_patch. טינקרבל אינה מדברת ואינה קובעת מה אריאלה תשאל. תיקון חדש גובר על מידע ישן. אל תנחשי עובדות שלא נאמרו.

כללי חילוץ חשובים: כאשר המשתמשת אומרת "עם הבת שלי" או "אני והבת שלי", שמרי adults=1, children=1 ו-travel_party_type=family, אלא אם גיל שכבר ידוע בשיחה מחייב סיווג תמחורי אחר. "עם הבן שלי" מקביל לכך. "עם בעלי" או "עם אשתי" משמע adults=2. המטרה היא לזכור את משמעות המשפט, לא להחזיר אותו כשאלה.

נרמול פנימי בלבד: vacation_type יכול להיות business / ski / standard. services כולל flight כשמדובר בטיסה. שדות אפשריים: vacation_type, services, destination_mode, destinations, departure_airports, date_mode, departure_date, return_date, outbound_month, return_month, date_flex_days, adults, children, child_ages, infants, travel_party_type, budget_mode, budget_amount, flight_preference, baggage, vacation_styles, lodging_type, rooms, bathrooms, hotel_rooms, lodging_budget_mode, lodging_budget_amount, pickup_location, dropoff_location, driver_age, car_type, transmission, car_budget_mode, car_budget_amount, car_features, notes.

החזירי JSON בלבד ובקיצור:
{"reply":"תשובת אריאלה הטבעית","profile_patch":{},"intent":"conversation","unclear":[]}
"""

QUESTIONS = {
    "purpose": "מה מתחשק לך לתכנן?",
    "destination": "יש לך כבר כיוון בראש, או שנחשוב יחד? 😊",
    "dates": "יש תקופה שמתאימה לך יותר?",
    "travelers": "מי מצטרף לחופשה?",
    "flight_preferences": "יש משהו שחשוב לך במיוחד בטיסה או בכבודה?",
    "budget": "יש תקציב לאדם שחשוב לך שאקח בחשבון?",
    "confirm": "יש עוד משהו שחשוב לך שאדע לפני החיפוש? 😊",
}


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
    context = {
        "current_date": date.today().isoformat(),
        "known_trip_context": profile,
    }
    result = _openai_json(
        key, model,
        SYSTEM + "\nהקשר פנימי שכבר ידוע; אל תחזרי עליו סתם:\n" + json.dumps(context, ensure_ascii=False),
        _conversation((history or [])[-6:], message),
        max_output_tokens=350,
    )
    if not isinstance(result, dict):
        result = {}
    result["profile_patch"] = _clean_patch(result.get("profile_patch"))
    if not isinstance(result.get("unclear"), list):
        result["unclear"] = []
    return result


def _safe_reply(result, stage):
    reply = str(result.get("reply") or "").strip()
    if reply:
        return reply
    return QUESTIONS.get(stage, "ספרי לי עוד 😊")


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
    reply = _safe_reply(result, stage)

    travel = _travel_matches(merged) if complete and ("attractions" in services or "route" in services) else []
    lodging_status = lodging_inventory_status() if complete and "lodging" in services else {
        "providers": [], "live_provider_count": 0, "live_inventory_available": False
    }
    return jsonify({
        "status": "success",
        "agent": "Ariella",
        "engine_version": ENGINE_VERSION,
        "reply": reply,
        "profile": merged,
        "intent": result.get("intent") or "conversation",
        "missing_question": "",
        "stage": stage,
        "show_purpose_picker": False,
        "show_service_picker": False,
        "ui_choice": None,
        "services": services,
        "ready_for_flights": complete and "flight" in services,
        "flight_search_started": False,
        "ready_for_lodging": complete and "lodging" in services,
        "ready_for_car": complete and "car" in services,
        "ready_for_travel": bool(travel),
        "intake_complete": complete,
        "requires_confirmation": complete,
        "confirmation_text": "עברו על כל הפרטים ב'החופשה שלי'. אם הכול נכון, אשרו יציאה לחיפוש.",
        "tinkerbell_handoff": _flight_handoff(merged),
        "travel_agent": {"attractions": travel},
        "lodging_schema": _load_json(_LODGING_SCHEMA_FILE, {}) if complete and "lodging" in services else {},
        "car_schema": _load_json(_CAR_SCHEMA_FILE, {}) if complete and "car" in services else {},
        "inventory_status": {"lodging": lodging_status, "car": "provider_pending"},
    })
