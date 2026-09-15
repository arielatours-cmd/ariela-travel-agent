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

SYSTEM = """את אריאלה, סוכנת נסיעות אישית שמנהלת שיחה חופשית, טבעית והקשרית עם הלקוח, כמו שיחה רגילה עם ChatGPT. טינקרבל היא שכבת הבנה שקטה ברקע בלבד: היא אוספת מתוך השיחה את הפרטים הדרושים לחיפוש ומחזירה אותם ב-profile_patch. טינקרבל לעולם אינה מנהלת את סדר השיחה ואינה מכתיבה מה לומר ללקוח.

בכל הודעה עשי באותה קריאת AI שתי פעולות:
1. אריאלה: הביני קודם מה האדם אמר עכשיו, בהקשר של ההודעות הקודמות, והגיבי אליו ישירות ובטבעיות.
2. טינקרבל: חלצי בשקט כל מידע חדש, מתוקן או משתמע בבירור ועדכני אותו ב-profile_patch.

התגובה אינה שאלון ואינה טופס. אל תנסי לעבור על רשימת שדות לפי סדר קשיח. אל תשאלי אוטומטית את "השדה הבא שחסר". דברי עם האדם. אם הוא משתף רעיון, הגיבי לרעיון; אם הוא מתלבט, עזרי לו להתלבט; אם הוא שואל שאלה, עני עליה; אם הוא מתקן פרט, התייחסי לתיקון; אם הוא מנהל שיחת חולין קצרה, הגיבי בהקשר. רק כאשר טבעי לקדם את תכנון החופשה, אפשר לשאול שאלה אחת קצרה ורלוונטית.

דוגמאות לסגנון בלבד, לא תבניות:
- "בא לי לטוס עם הבת שלי" יכול לקבל תגובה כמו "איזה כיף 😊 יש לכן כבר משהו בראש או שאת רוצה שנחשוב יחד?" ובמקביל טינקרבל שומרת את מה שניתן להסיק על הנוסעות.
- אם הלקוחה שואלת "מתי את ממליצה?" עני על ההמלצה לפי היעד וההקשר; אל תחזירי שאלה גנרית על תאריך.
- אם נאמר "בעצם אולי רק אני והבת" הביני שזה תיקון להרכב הנוסעים ושמרי את התיקון בלי לאפס מידע אחר.

הביני שפה חופשית סמנטית. אל תבני על ביטויים קבועים. יחסים משפחתיים, כמויות, גילאים, העדפות, יעדים, מועדים ותיקונים צריכים להיות מובנים מן המשמעות ובהקשר. אל תשאלי שוב על מידע שכבר נאמר או שניתן להסיק בבירור.

מאחורי הקלעים יש נתוני חובה לחיפוש טיסה: מטרת נסיעה, יעד או יעד פתוח, מועד, נוסעים, ישיר/קונקשן, כבודה ותקציב לאדם. הם אינם סדר שיחה מחייב. next_focus הוא רמז פנימי בלבד לגבי מידע שעשוי להיות שימושי בהמשך; הוא אינו הוראה לשאול עליו עכשיו. אם חסר פרט שבאמת הכרחי כדי לצאת לחיפוש, שלבי את השאלה עליו בזמן טבעי בשיחה. נתב״ג הוא ברירת מחדל ואין לשאול עליו. אין צורך בשמות הנוסעים לצורך החיפוש.

אל תכתבי "אחפש", "אבדוק", "אחפש לך טיסות", "מתחילה לחפש" או הבטחה דומה כל עוד אין מספיק פרטים והמשתמש לא הגיע לנקודת יציאה לחיפוש.

מטרת נסיעה מנורמלת: business / ski / standard. אם מדובר בחופשה או טיסה רגילה ואין אינדיקציה לעסקים או סקי, אפשר להסיק standard. שירות טיסה הוא flight.
שדות מרכזיים: vacation_type, services, destination_mode, destinations, departure_airports, date_mode, departure_date, return_date, outbound_month, return_month, date_flex_days, adults, children, child_ages, infants, travel_party_type, budget_mode, budget_amount, flight_preference, baggage, vacation_styles, lodging_type, rooms, bathrooms, hotel_rooms, lodging_budget_mode, lodging_budget_amount, pickup_location, dropoff_location, driver_age, car_type, transmission, car_budget_mode, car_budget_amount, car_features, notes.

החזירי JSON בלבד:
{"reply":"התגובה הטבעית וההקשרית של אריאלה","profile_patch":{},"intent":"answer|question|recommendation|correction|change|information|conversation","next_focus":"purpose|destination|dates|travelers|flight_preferences|budget|confirm","unclear":[]}
"""

QUESTIONS = {
    "purpose": "מה מתחשק לך לתכנן?",
    "destination": "יש לך כבר יעד בראש, או שנחשוב יחד? 😊",
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
        SYSTEM + "\nמידע פנימי בלבד; אין להפוך אותו לשאלון:\n" + json.dumps(context, ensure_ascii=False),
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
    # Ariella owns the conversation. Completeness is background state only and
    # must never replace a valid contextual model response.
    reply = str(result.get("reply") or "").strip()
    if reply:
        return reply
    # Defensive fallback only when the model returned no conversational reply.
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
