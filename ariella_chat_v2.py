import json
import os
from datetime import date

from flask import Blueprint, jsonify, request

from travel_agents import (
    _member_context, _persist_gender, _normalize_services, _next_question,
    _travel_matches, _ui_choice, _flight_handoff, _load_json,
    _LODGING_SCHEMA_FILE, _CAR_SCHEMA_FILE, _openai_json, _conversation,
)
from lodging_providers import lodging_inventory_status

ariella_chat_v2 = Blueprint("ariella_chat_v2", __name__)

SYSTEM = """את אריאלה, סוכנת הנסיעות האישית שמנהלת את השיחה עם הלקוח. טינקרבל היא שכבת ההבנה השקטה שלך: באותה קריאה את גם מנהלת שיחה טבעית וגם מעדכנת ברקע את תיק החופשה.

כלל עליון: זו שיחה בין בני אדם, לא שאלון ולא טופס. בכל הודעה הביני קודם מה הלקוח התכוון לעשות עכשיו: לענות, לשאול אותך שאלה, לבקש המלצה או הסבר, לתקן מידע קודם, לשנות החלטה, להתלבט, או למסור כמה פרטים יחד. אם הלקוח שאל שאלה או ביקש המלצה/הסבר — עני על זה קודם. אסור ששדה חסר ידרוס את התשובה לשאלה שלו.

במקביל, חלצי סמנטית כל מידע חדש שנאמר ועדכני אותו ב-profile_patch. אל תסתמכי על רשימת ניסוחים קשיחה. הביני יחסים וכמויות מתוך השפה הטבעית וההקשר. לדוגמה, משפט שמספר שהלקוחה נוסעת עם בעלה ובת בת 17 משמעו 2 מבוגרים, ילדה אחת, child_ages=[17], travel_party_type=family. זו דוגמה להבנה סמנטית בלבד, לא תבנית שיש לחפש. אם בהמשך הלקוח מתקן מידע, עדכני רק את מה שתוקן.

אל תשאלי שוב מידע שכבר קיים בפרופיל. אחרי שמטרת הנסיעה ידועה, פרטי הבסיס הם יעד, מועד ונוסעים. אם חלק מהם ידוע, שאלי באופן טבעי רק על מה שחסר. רק כששלושתם ידועים עוברים להעדפות הטיסה. ישיר/קונקשן וכבודה נשאלים יחד אם שניהם חסרים. תקציב לאדם הוא שאלת הטיסה האחרונה. נתב״ג הוא ברירת המחדל למשתמש ישראלי ואין צורך לשאול שדה יציאה אלא אם הלקוח מבקש אחרת.

אל תבטיחי שחיפוש התחיל ואל תכתבי 'אחפש', 'אבדוק' או 'מתחילה לחפש' בזמן איסוף הפרטים. החיפוש מתחיל רק לאחר שכל נתוני החובה הושלמו ואושרו.

ה-profile הקיים הוא מקור האמת למה שכבר ידוע. profile_patch מכיל רק מידע חדש או מתוקן מההודעה הנוכחית. ערכים פנימיים יכולים להיות מנורמלים באנגלית, אך reply תמיד בשפת הלקוח.

מטרת נסיעה: business / ski / standard. שירותים: flight / lodging / attractions / route / car. שדות מרכזיים: vacation_type, services, destination_mode, destinations, departure_airports, date_mode, departure_date, return_date, outbound_month, return_month, date_flex_days, adults, children, child_ages, infants, travel_party_type, budget_mode, budget_amount, flight_preference, baggage, vacation_styles, lodging_type, rooms, bathrooms, hotel_rooms, lodging_budget_mode, lodging_budget_amount, pickup_location, dropoff_location, driver_age, car_type, transmission, car_budget_mode, car_budget_amount, car_features, notes.

החזירי JSON בלבד במבנה:
{"reply":"התשובה הטבעית ללקוח","profile_patch":{},"intent":"answer|question|recommendation|correction|change|information|conversation","unclear":[]}
"""


def _clean_patch(value):
    if not isinstance(value, dict):
        return {}
    # None means "not learned". Empty values are allowed only when the model is
    # explicitly correcting/removing a previous choice.
    return {k: v for k, v in value.items() if v is not None}


def _missing_context(profile):
    question, stage = _next_question(profile)
    return {"stage": stage, "suggested_missing_question": question}


def _single_pass(message, history, profile):
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    model = os.getenv("ARIELLA_MODEL", "gpt-5.6-luna").strip()
    context = {
        "current_date": date.today().isoformat(),
        "profile": profile,
        "missing_before_message": _missing_context(profile),
    }
    result = _openai_json(
        key,
        model,
        SYSTEM + "\nמידע פנימי לפני ההודעה הנוכחית:\n" + json.dumps(context, ensure_ascii=False),
        _conversation(history, message),
        max_output_tokens=900,
    )
    if not isinstance(result, dict):
        result = {}
    result["profile_patch"] = _clean_patch(result.get("profile_patch"))
    if not isinstance(result.get("unclear"), list):
        result["unclear"] = []
    return result


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

    # Israel/TLV is the product default; it should not consume a conversational turn.
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

    next_question, stage = _next_question(merged)
    complete = stage == "confirm"
    services = merged.get("services") or []
    reply = str(result.get("reply") or "").strip()
    # The deterministic completeness check is advisory only. It never replaces a
    # natural answer. If the model returned no text, use the missing question as a
    # safety fallback; otherwise Ariella owns the conversation.
    if not reply:
        reply = next_question or "יש עוד משהו שחשוב לכם שאדע לפני שנמשיך?"

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
        "missing_question": next_question,
        "stage": stage,
        "show_purpose_picker": False,
        "show_service_picker": False,
        "ui_choice": _ui_choice(stage, next_question, merged),
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
