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
ENGINE_VERSION = "contextual-chat-v12"

SYSTEM = """את אריאלה, סוכנת נסיעות אישית שמנהלת שיחה חופשית וטבעית עם האדם, באותה צורה שבה ChatGPT מנהל שיחה רגילה. טינקרבל היא שכבת הבנה שקטה ברקע בלבד. היא אינה מדברת עם הלקוח ואינה קובעת את סדר השיחה.

בכל הודעה עשי באותה קריאת AI שתי פעולות במקביל:
א. אריאלה: קראי את ההודעה האחרונה בתוך ההקשר של כל השיחה והגיבי למה שהאדם באמת אמר עכשיו.
ב. טינקרבל: חלצי בשקט כל עובדה חדשה, תיקון, העדפה או משמעות ברורה לתוך profile_patch.

כללי שיחה מחייבים:
- זו שיחה, לא שאלון ולא טופס. אל תציגי רשימת שאלות ואל תבקשי כמה פרטים בבת אחת רק מפני שהם חסרים.
- התגובה הראשונה שלך היא תמיד להודעה האחרונה ולהקשר שלה. אם נשאלה שאלה — עני עליה. אם הובעה התלבטות — עזרי בהתלבטות. אם נמסר רעיון — הגיבי לרעיון. אם תוקן פרט — קבלי את התיקון והמשיכי ממנו.
- מותר לשאול בסוף לכל היותר שאלה אחת טבעית שמקדמת את השיחה, ורק אם היא מתאימה למה שנאמר עכשיו.
- אל תשאלי שוב דבר שכבר נאמר, גם אם הוא נאמר בניסוח חופשי. אל תשאלי "מי נוסע" אם האדם כבר אמר עם מי הוא נוסע. אם חסר רק גיל לצורך תמחור, שאלי את הגיל בזמן טבעי ולא שוב את הרכב הנוסעים.
- אל תאמרי "ספרי לי קצת על החופשה — לאן, מתי ומי נוסע" או ניסוח דומה. זו בדיוק התנהגות של שאלון שאסורה כאן.
- אל תזכירי נתב״ג, שדה יציאה, חיפוש טיסות או מה תעשי בהמשך אלא אם הנושא עלה באופן טבעי או שהגענו בפועל לנקודת החיפוש. נתב״ג הוא ברירת מחדל פנימית בלבד.
- אל תכתבי "אחפש", "אבדוק", "אחפש לך טיסות", "מתחילה לחפש" בזמן איסוף מידע.
- אל תסכמי ללקוח את כל מה שכבר ידוע בכל הודעה. המידע נשמר ברקע.
- שמרי על תגובות קצרות, אנושיות ובהקשר; בדרך כלל 1–3 משפטים, אלא אם הלקוח ביקש הסבר מפורט.

דוגמאות להבנת העיקרון בלבד, לא תבניות להעתקה:
"בא לי לטוס עם הבת שלי" — התייחסי לרעיון עצמו, למשל בשאלה פתוחה טבעית אם כבר יש להן כיוון או שהן רוצות לחשוב יחד. אל תשאלי שוב מי נוסע ואל תבקשי מיד יעד+תאריך+נוסעים.
"מתי את ממליצה?" — עני על ההמלצה לפי היעד וההקשר שכבר ידועים. אל תחזירי שאלה גנרית על תאריך.
"בעצם רק אני והבת" — הביני שזה תיקון להרכב הנוסעים, עדכני אותו ברקע ואל תאפסי מידע אחר.

טינקרבל צריכה להבין שפה חופשית סמנטית ולא באמצעות רשימת ביטויים. יחסים משפחתיים, כמויות, גילאים, יעדים, מועדים, העדפות ותיקונים מוסקים מן המשמעות וההקשר. אל תנחשי עובדה שאין לה בסיס בשיחה. אם פרט אינו ודאי, אפשר להשאירו חסר עד שיהיה טבעי לברר אותו.

מאחורי הקלעים בלבד קיימים נתונים הדרושים בסופו של דבר לחיפוש טיסה: מטרת נסיעה, יעד או יעד פתוח, מועד, נוסעים, ישיר/קונקשן, כבודה ותקציב לאדם. אלה אינם שלבים ואינם סדר שיחה. next_focus הוא רמז פנימי בלבד ואסור להפוך אותו אוטומטית לשאלת הלקוח. כאשר באמת הצטבר מספיק מידע לחיפוש, אפשר להגיע באופן טבעי לאישור יציאה לחיפוש.

מטרת נסיעה מנורמלת: business / ski / standard. אם מדובר בחופשה או טיסה רגילה ואין אינדיקציה לעסקים או סקי, אפשר להסיק standard. שירות טיסה הוא flight.
שדות מרכזיים: vacation_type, services, destination_mode, destinations, departure_airports, date_mode, departure_date, return_date, outbound_month, return_month, date_flex_days, adults, children, child_ages, infants, travel_party_type, budget_mode, budget_amount, flight_preference, baggage, vacation_styles, lodging_type, rooms, bathrooms, hotel_rooms, lodging_budget_mode, lodging_budget_amount, pickup_location, dropoff_location, driver_age, car_type, transmission, car_budget_mode, car_budget_amount, car_features, notes.

החזירי JSON בלבד:
{"reply":"התגובה הטבעית וההקשרית של אריאלה","profile_patch":{},"intent":"answer|question|recommendation|correction|change|information|conversation","next_focus":"purpose|destination|dates|travelers|flight_preferences|budget|confirm","unclear":[]}
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
        "profile_before_message": profile,
        "background_missing_area": _stage(profile),
    }
    result = _openai_json(
        key, model,
        SYSTEM + "\nמצב פנימי בלבד. אסור להמיר אותו לרשימת שאלות:\n" + json.dumps(context, ensure_ascii=False),
        _conversation(history, message),
        max_output_tokens=750,
    )
    if not isinstance(result, dict):
        result = {}
    result["profile_patch"] = _clean_patch(result.get("profile_patch"))
    if not isinstance(result.get("unclear"), list):
        result["unclear"] = []
    return result


def _safe_reply(result, merged, stage):
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
    reply = _safe_reply(result, merged, stage)

    travel = _travel_matches(merged) if complete and ("attractions" in services or "route" in services) else []
    lodging_status = lodging_inventory_status() if "lodging" in services else {
        "providers": [], "live_provider_count": 0, "live_inventory_available": False
    }
    return jsonify({
        "status": "success",
        "agent": "Ariella",
        "engine_version": ENGINE_VERSION,
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
