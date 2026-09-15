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

SYSTEM = """את אריאלה, סוכנת הנסיעות האישית שמדברת עם הלקוח. טינקרבל היא שכבת ההבנה השקטה שלך ופועלת ברקע באותה קריאת AI.

בכל הודעה עשי שתי פעולות יחד:
1. הביני סמנטית את כל מה שנאמר ועדכני profile_patch רק במידע חדש או מתוקן.
2. נהלי שיחה טבעית ואנושית בהתאם לכוונת הלקוח ולהקשר.

זו אינה מערכת של משפטים קבועים. הביני שפה חופשית, יחסים, כמויות, תיקונים ושאלות לפי משמעותם. אם הלקוח מתאר מי נוסע, הסיקי את הרכב הנוסעים מן המשמעות. לדוגמה בלבד, נסיעה של הלקוחה עם בעלה ובת בת 17 משמעותה שני מבוגרים, ילדה אחת בת 17 ומשפחה. אל תחפשי את הניסוח הזה כתבנית — הפעילי אותה הבנה על כל ניסוח טבעי.

אם הלקוח שואל שאלה, מבקש המלצה, הסבר או מתלבט — עני על זה קודם. אסור ששדה חסר ידרוס שאלה של הלקוח. אפשר בסוף התשובה לשלב שאלה קצרה שמקדמת את החופשה.

אם ההודעה בעיקר מוסרת/מתקנת מידע, התגובה צריכה להתבסס על המידע החדש כאילו profile_patch כבר מוזג לפרופיל. אל תשאלי על פרט שמסרת כרגע או שכבר היה ידוע. next_focus צריך לציין איזה תחום נכון להשלים אחרי המיזוג.

סדר נתוני הטיסה: מטרת נסיעה -> יעד -> מועד -> נוסעים -> ישיר/קונקשן וכבודה -> תקציב לאדם. אם התקבל מידע חלקי, משלימים רק את החסר. ישיר/קונקשן וכבודה נשאלים יחד כאשר שניהם חסרים. נתב״ג הוא ברירת מחדל ואין לשאול עליו. אין לשאול שמות נוסעים כחלק מנתוני החובה.

אל תכתבי 'אחפש', 'אבדוק', 'אחפש לך טיסות', 'מתחילה לחפש' או כל הבטחה לחיפוש בזמן איסוף הפרטים. חיפוש מתחיל רק לאחר השלמת הפרטים ואישור.

מטרת נסיעה: business / ski / standard. אם הלקוח אומר שהוא מחפש טיסה/חופשה משפחתית רגילה ואין אינדיקציה לעסקים או סקי, אפשר להסיק standard. שירות טיסה הוא flight.
שדות מרכזיים: vacation_type, services, destination_mode, destinations, departure_airports, date_mode, departure_date, return_date, outbound_month, return_month, date_flex_days, adults, children, child_ages, infants, travel_party_type, budget_mode, budget_amount, flight_preference, baggage, vacation_styles, lodging_type, rooms, bathrooms, hotel_rooms, lodging_budget_mode, lodging_budget_amount, pickup_location, dropoff_location, driver_age, car_type, transmission, car_budget_mode, car_budget_amount, car_features, notes.

החזירי JSON בלבד:
{"reply":"תשובה טבעית","profile_patch":{},"intent":"answer|question|recommendation|correction|change|information|conversation","next_focus":"purpose|destination|dates|travelers|flight_preferences|budget|confirm","unclear":[]}
"""

QUESTIONS = {
    "purpose": "מה מטרת הטיסה? למשל עסקים, בילוי עם חברים, טיול משפחתי או חופשת סקי.",
    "destination": "לאן תרצו לטוס? אם עדיין לא החלטתם, אני יכולה גם לעזור לבחור יעד 😊",
    "dates": "ומתי תרצו לטוס? אפשר תאריכים מדויקים או חודש מועדף.",
    "travelers": "ומי נוסע איתכם?",
    "flight_preferences": "ומה חשוב לכם מבחינת הטיסה? חשוב לכם לטוס ישיר, או שגם קונקשן יכול להתאים? ואיזו כבודה תצטרכו — תיק יד, טרולי או מזוודה?",
    "budget": "ולסיום, יש תקציב לאדם שתרצו שאשתדל לעמוד בו, או שאין מגבלת תקציב?",
    "confirm": "יש עוד משהו שחשוב לכם בחופשה שאדע לפני שמתחילים לחפש? 😊",
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
        "profile_before_message": profile,
        "stage_before_message": _stage(profile),
    }
    result = _openai_json(
        key, model,
        SYSTEM + "\nמידע פנימי לפני ההודעה:\n" + json.dumps(context, ensure_ascii=False),
        _conversation(history, message),
        max_output_tokens=850,
    )
    if not isinstance(result, dict):
        result = {}
    result["profile_patch"] = _clean_patch(result.get("profile_patch"))
    if not isinstance(result.get("unclear"), list):
        result["unclear"] = []
    return result


def _safe_reply(result, merged, stage):
    reply = str(result.get("reply") or "").strip()
    intent = str(result.get("intent") or "conversation").strip().lower()
    model_focus = str(result.get("next_focus") or "").strip()

    # Questions/recommendations belong to Ariella: answer the customer, never let
    # the completeness engine overwrite that answer.
    if intent in {"question", "recommendation", "answer", "conversation"} and reply:
        return reply

    # For information/corrections the backend verifies the model's proposed next
    # focus against the profile AFTER extraction. This prevents re-asking a field
    # that Tinkerbell has just learned, without relying on Hebrew phrase patterns.
    if model_focus != stage:
        return QUESTIONS[stage]
    return reply or QUESTIONS[stage]


@ariella_chat_v2.post("/api/ariella/chat")
def ariella_chat():
    body = request.get_json(silent=True) or {}
    message = str(body.get("message") or "").strip()
    if not message:
        return jsonify({"status": "error", "message": "message is required"}), 400

    profile = dict(body.get("profile") if isinstance(body.get("profile"), dict) else {})
    history = body.get("history") if isinstance(body.get("history"), list) else []
    member = _member_context()
    if member:
        if member.get("gender") and not profile.get("customer_gender"):
            profile["customer_gender"] = member.get("gender")
        profile["known_companions"] = member.get("companions") or []
        if profile.get("customer_gender"):
            _persist_gender(member["id"], profile.get("customer_gender"))

    if not profile.get("departure_airports"):
        profile["departure_airports"] = ["TLV"]

    try:
        result = _single_pass(message, history, profile)
    except Exception as exc:
        return jsonify({"status": "error", "message": "אריאלה לא זמינה כרגע.", "detail": str(exc)}), 503

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
    reply = _safe_reply(result, merged, stage)

    travel = _travel_matches(merged) if complete and ("attractions" in services or "route" in services) else []
    lodging_status = lodging_inventory_status() if "lodging" in services else {
        "providers": [], "live_provider_count": 0, "live_inventory_available": False
    }
    return jsonify({
        "status": "success",
        "agent": "Ariella",
        "reply": reply,
        "profile": merged,
        "intent": result.get("intent") or "conversation",
        "missing_question": QUESTIONS[stage] if not complete else "",
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
        "lodging_schema": _load_json(_LODGING_SCHEMA_FILE, {}) if "lodging" in services else {},
        "car_schema": _load_json(_CAR_SCHEMA_FILE, {}) if "car" in services else {},
        "inventory_status": {"lodging": lodging_status, "car": "provider_pending"},
    })
