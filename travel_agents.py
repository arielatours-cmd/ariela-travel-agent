import json
import os
from datetime import date
from pathlib import Path

import requests
from flask import Blueprint, jsonify, request

travel_agents = Blueprint("travel_agents", __name__)

_DATA_DIR = Path(__file__).resolve().parent / "data"
_ATTRACTION_FILES = [_DATA_DIR / "attractions.json", _DATA_DIR / "attractions_global30.json"]
_LODGING_SCHEMA_FILE = _DATA_DIR / "lodging_preferences.json"
_CAR_SCHEMA_FILE = _DATA_DIR / "car_preferences.json"

SERVICE_LABELS = {
    "flight": "טיסות",
    "lodging": "לינה",
    "attractions": "אטרקציות",
    "route": "בניית מסלול",
    "car": "השכרת רכב",
}

ARIELLA_SYSTEM = """את אריאלה, סוכנת הנסיעות הראשית והיחידה שמדברת עם הלקוח של ARIELA AI TRAVEL.
את מנהלת שיחה טבעית וקצרה בעברית (או בשפת הלקוח).
שמרי בשקט את הנתונים במבנה החיפוש. אל תחזרי על מידע שהלקוח כבר מסר ואל תסכמי אותו.
אל תכתבי מה את יכולה לעשות, מה תעשי בעתיד, או ניסוחים כגון 'אבדוק', 'אחפש', 'מתחילה לבדוק'.
הלקוח יכול לבחור שירות אחד או יותר: טיסות, לינה, אטרקציות, בניית מסלול והשכרת רכב.
החזירי JSON בלבד עם המפתחות reply ו-profile. profile מצטבר ואסור למחוק מידע קודם אלא אם הלקוח תיקן אותו.
שדות עיקריים: services, destination_mode, destinations, departure_airports, date_mode, departure_date, return_date, outbound_month, return_month, date_flex_days, adults, children, child_ages, infants, budget_mode, budget_amount, flight_preference, baggage, vacation_styles, nature, urban, shopping, nightlife, accessibility, pace, max_drive_minutes, lodging_type, rooms, bathrooms, hotel_rooms, beds, lodging_budget_mode, lodging_budget_amount, location_priority, lodging_amenities, meal_plan, star_rating, cancellation, car_needed, pickup_location, dropoff_location, pickup_datetime, dropoff_datetime, driver_age, car_type, passenger_capacity, large_bags, transmission, car_budget_mode, car_budget_amount, car_features, fuel_policy, one_way, notes.
"""

TINKERBELL_SYSTEM = """את טינקרבל, סוכנת פנימית. אינך מדברת עם הלקוח.
פרשי ניסוח חופשי ושגיאות כתיב ומפי רק מידע שנאמר בפועל לשדות profile.
שירותים: טיסה/טיסות=>flight; מלון/דירה/וילה/לינה=>lodging; אטרקציות=>attractions; מסלול/תכנון טיול=>route; רכב/השכרת רכב=>car.
'אין תקציב'/'בלי הגבלת תקציב'/'לא משנה המחיר' => budget_mode=unlimited; ובהקשר לינה או רכב השתמשי בשדה התקציב המתאים.
כאשר נמסרים יום וחודש ללא שנה, הסיקי את השנה העתידית הקרובה לפי current_date וצרי תאריכים מלאים.
אל תנחשי מידע שלא נאמר. החזירי JSON בלבד: profile_patch, interpretation, unclear.
"""


def _openai_json(key, model, developer_text, conversation, max_output_tokens=1000):
    payload = {
        "model": model,
        "input": [{"role": "developer", "content": developer_text}] + conversation,
        "text": {"format": {"type": "json_object"}},
        "max_output_tokens": max_output_tokens,
    }
    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=payload,
        timeout=35,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"OpenAI API error {response.status_code}: {response.text[:1200]}")
    body = response.json()
    text = body.get("output_text")
    if not text:
        chunks = []
        for out in body.get("output") or []:
            for part in out.get("content") or []:
                if part.get("type") == "output_text":
                    chunks.append(part.get("text") or "")
        text = "".join(chunks)
    return json.loads(text or "{}")


def _conversation(history, message):
    items = []
    for item in (history or [])[-12:]:
        role = "assistant" if item.get("role") == "assistant" else "user"
        items.append({"role": role, "content": str(item.get("content") or "")[:2500]})
    items.append({"role": "user", "content": message})
    return items


def _call_tinkerbell(message, history, profile):
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    model = os.getenv("ARIELLA_MODEL", "gpt-5.6-luna").strip()
    context = dict(profile or {})
    context["current_date"] = date.today().isoformat()
    result = _openai_json(
        key, model,
        TINKERBELL_SYSTEM + "\nפרופיל קיים:\n" + json.dumps(context, ensure_ascii=False),
        _conversation(history, message),
        max_output_tokens=700,
    )
    if not isinstance(result.get("profile_patch"), dict):
        result["profile_patch"] = {}
    if not isinstance(result.get("unclear"), list):
        result["unclear"] = []
    return result


def _call_ariella(message, history, profile, tinkerbell):
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    model = os.getenv("ARIELLA_MODEL", "gpt-5.6-luna").strip()
    internal = {
        "profile": profile or {},
        "current_date": date.today().isoformat(),
        "interpretation": tinkerbell.get("interpretation") or "",
        "unclear": tinkerbell.get("unclear") or [],
    }
    result = _openai_json(
        key, model,
        ARIELLA_SYSTEM + "\nמידע פנימי:\n" + json.dumps(internal, ensure_ascii=False),
        _conversation(history, message),
        max_output_tokens=800,
    )
    if not isinstance(result.get("profile"), dict):
        result["profile"] = dict(profile or {})
    return result


def _normalize_services(value):
    if isinstance(value, str):
        value = [value]
    out = []
    for raw in value or []:
        token = str(raw or "").strip().lower()
        aliases = {
            "flights": "flight", "טיסה": "flight", "טיסות": "flight",
            "hotel": "lodging", "hotels": "lodging", "לינה": "lodging", "מלון": "lodging", "דירה": "lodging",
            "attraction": "attractions", "אטרקציה": "attractions", "אטרקציות": "attractions",
            "itinerary": "route", "מסלול": "route", "תכנון מסלול": "route",
            "rental_car": "car", "רכב": "car", "השכרת רכב": "car",
        }
        token = aliases.get(token, token)
        if token in SERVICE_LABELS and token not in out:
            out.append(token)
    return out


def _has_destination(p):
    return bool(p.get("destinations")) or p.get("destination_mode") in {"open", "ariella", "flexible"}


def _has_dates(p):
    return bool((p.get("departure_date") and p.get("return_date")) or p.get("outbound_month"))


def _has_travelers(p):
    try:
        return int(p.get("adults") or 0) > 0
    except (TypeError, ValueError):
        return False


def _has_budget(p, prefix=""):
    mode = p.get(f"{prefix}budget_mode")
    amount = p.get(f"{prefix}budget_amount")
    return bool(mode or amount not in (None, ""))


def _shared_question(p):
    if not _has_destination(p):
        return "לאן תרצו לנסוע? אם אין יעד מסוים, אפשר לבחור פתוחים להצעות."
    if not _has_dates(p):
        return "מתי תרצו לנסוע? אפשר תאריכים מדויקים או חודש מועדף."
    if not _has_travelers(p):
        return "כמה נוסעים יהיו, וכמה מהם ילדים או תינוקות?"
    return ""


def _flight_question(p):
    if not _has_budget(p):
        return "יש מגבלת תקציב לאדם?"
    if not p.get("departure_airports"):
        return "מאיזה שדה תעופה תרצו לצאת?"
    if not p.get("flight_preference"):
        return "חשוב לכם לטוס ישיר, או שגם קונקשן מתאים?"
    if not p.get("baggage"):
        return "איזו כבודה תרצו לכלול — תיק יד, טרולי או מזוודה?"
    return ""


def _lodging_question(p):
    lodging_type = str(p.get("lodging_type") or "")
    if not lodging_type:
        return "איזה סוג לינה אתם מעדיפים — מלון, דירה, וילה, ריזורט או שלא משנה?"
    if lodging_type in {"apartment", "villa", "דירה", "וילה"}:
        if not p.get("rooms"):
            return "כמה חדרי שינה אתם צריכים?"
        if not p.get("bathrooms"):
            return "כמה חדרי רחצה חשוב שיהיו?"
    if lodging_type in {"hotel", "resort", "מלון", "ריזורט"} and not p.get("hotel_rooms"):
        return "כמה חדרי מלון אתם צריכים?"
    if not _has_budget(p, "lodging_"):
        return "יש מגבלת תקציב ללינה — ללילה או לכל השהות?"
    if p.get("location_priority") in (None, "", []):
        return "מה הכי חשוב במיקום — מרכז, שקט, חוף, תחבורה, אטרקציות או חניה?"
    if p.get("lodging_amenities") in (None, "", []):
        return "מה חשוב שיהיה במקום — למשל מטבח, בריכה, חניה, מעלית, מכונת כביסה, ארוחת בוקר או נגישות?"
    return ""


def _car_question(p):
    if not p.get("pickup_location"):
        return "איפה תרצו לאסוף את הרכב?"
    if not p.get("dropoff_location"):
        return "איפה תרצו להחזיר את הרכב?"
    if not p.get("driver_age"):
        return "מה גיל הנהג הראשי?"
    if not p.get("car_type"):
        return "איזה רכב מתאים לכם — קטן, משפחתי, SUV, 7 מקומות או שלא משנה?"
    if not p.get("transmission"):
        return "חשוב לכם רכב אוטומטי, או שלא משנה?"
    if not _has_budget(p, "car_"):
        return "יש מגבלת תקציב לרכב — ליום או לכל התקופה?"
    if p.get("car_features") in (None, "", []):
        return "יש משהו שחייב להיות ברכב — למשל מושב תינוק, בוסטר, נהג נוסף, ביטוח מלא או תא מטען גדול? אם לא, כתבו שלא."
    return ""


def _experience_question(p):
    if p.get("vacation_styles") in (None, "", []):
        return "מה תרצו לשלב בחופשה — טבע, ערים, חופים, שופינג, חיי לילה, אקסטרים או שילוב?"
    if "route" in _normalize_services(p.get("services")) and not p.get("pace"):
        return "איזה קצב מתאים לכם — רגוע, בינוני או עמוס?"
    return ""


def _next_question(p):
    services = _normalize_services(p.get("services"))
    if not services:
        return "", "services"
    shared = _shared_question(p)
    if shared:
        return shared, "shared"
    if "flight" in services:
        q = _flight_question(p)
        if q:
            return q, "flight"
    if "lodging" in services:
        q = _lodging_question(p)
        if q:
            return q, "lodging"
    if "car" in services:
        q = _car_question(p)
        if q:
            return q, "car"
    if "attractions" in services or "route" in services:
        q = _experience_question(p)
        if q:
            return q, "experience"
    return "", "complete"


def _load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _load_attractions():
    combined = []
    seen = set()
    for path in _ATTRACTION_FILES:
        data = _load_json(path, {})
        items = data.get("attractions", data if isinstance(data, list) else [])
        for row in items:
            key = (str(row.get("מדינה") or ""), str(row.get("עיר/בסיס") or ""), str(row.get("שם האטרקציה") or ""))
            if key in seen:
                continue
            seen.add(key)
            combined.append(row)
    return combined


def _truthy(value):
    return str(value or "").strip().lower() in {"כן", "yes", "true", "1", "חלקית"}


def _travel_matches(profile, limit=8):
    destinations = [str(x).lower() for x in (profile.get("destinations") or [])]
    styles = {str(x).lower() for x in (profile.get("vacation_styles") or [])}
    rows = []
    for row in _load_attractions():
        country = str(row.get("מדינה") or "").lower()
        city = str(row.get("עיר/בסיס") or "").lower()
        if destinations and not any(d in country or d in city or country in d or city in d for d in destinations):
            continue
        score = 0
        reasons = []
        checks = [
            (profile.get("nature") or "טבע" in styles, "טבע ונופים", "טבע"),
            (profile.get("urban") or "עירוני" in styles, "טיול עירוני", "עירוני"),
            (profile.get("shopping") or "שופינג" in styles, "שופינג", "שופינג"),
            (int(profile.get("children") or 0) > 0, "מתאים לילדים", "ילדים"),
        ]
        for wanted, field, label in checks:
            if wanted and _truthy(row.get(field)):
                score += 3
                reasons.append(label)
            elif wanted and str(row.get(field) or "").strip() == "לא":
                score -= 3
        rows.append((score, row, reasons))
    rows.sort(key=lambda x: x[0], reverse=True)
    return [{
        "name": row.get("שם האטרקציה"), "country": row.get("מדינה"), "region": row.get("אזור/מחוז"),
        "city": row.get("עיר/בסיס"), "type": row.get("סוג ראשי"), "score": score, "reasons": reasons,
        "duration": row.get("משך מומלץ"), "difficulty": row.get("רמת קושי"), "accessibility": row.get("נגישות"),
        "price": row.get("מחיר/הערת מחיר"), "official_url": row.get("אתר רשמי"),
        "booking_url": row.get("קישור הזמנה/כרטיסים"), "notes": row.get("הערות"),
    } for score, row, reasons in rows[:limit]]


def _flight_handoff(p):
    return {
        "destination_mode": p.get("destination_mode") or ("specific" if p.get("destinations") else "open"),
        "destinations": p.get("destinations") or [], "departure_airports": p.get("departure_airports") or [],
        "date_mode": p.get("date_mode"), "departure_date": p.get("departure_date"), "return_date": p.get("return_date"),
        "outbound_month": p.get("outbound_month"), "return_month": p.get("return_month"), "date_flex_days": p.get("date_flex_days") or 0,
        "adults": p.get("adults"), "children": p.get("children") or 0, "budget_mode": p.get("budget_mode"),
        "budget_amount": p.get("budget_amount"), "flight_preference": p.get("flight_preference"), "baggage": p.get("baggage"),
    }


@travel_agents.post("/api/ariella/chat")
def ariella_chat():
    body = request.get_json(silent=True) or {}
    message = str(body.get("message") or "").strip()
    if not message:
        return jsonify({"status": "error", "message": "message is required"}), 400
    profile = body.get("profile") if isinstance(body.get("profile"), dict) else {}
    history = body.get("history") if isinstance(body.get("history"), list) else []
    try:
        tinkerbell = _call_tinkerbell(message, history, profile)
        normalized = dict(profile)
        normalized.update({k: v for k, v in tinkerbell.get("profile_patch", {}).items() if v not in (None, "", [])})
        normalized["services"] = _normalize_services(normalized.get("services"))
        result = _call_ariella(message, history, normalized, tinkerbell)
    except Exception as exc:
        return jsonify({"status": "error", "message": "אריאלה לא זמינה כרגע.", "detail": str(exc)}), 503

    merged = dict(normalized)
    merged.update({k: v for k, v in result.get("profile", {}).items() if v not in (None, "", [])})
    merged["services"] = _normalize_services(merged.get("services"))
    next_question, stage = _next_question(merged)
    complete = stage == "complete"
    services = merged.get("services") or []
    travel = _travel_matches(merged) if complete and ("attractions" in services or "route" in services) else []

    return jsonify({
        "status": "success", "agent": "Ariella", "reply": next_question, "profile": merged,
        "stage": stage, "show_service_picker": stage == "services", "services": services,
        "ready_for_flights": complete and "flight" in services, "flight_search_started": False,
        "ready_for_lodging": complete and "lodging" in services,
        "ready_for_car": complete and "car" in services,
        "ready_for_travel": bool(travel), "intake_complete": complete,
        "show_assistance": False, "tinkerbell_handoff": _flight_handoff(merged),
        "travel_agent": {"attractions": travel},
        "lodging_schema": _load_json(_LODGING_SCHEMA_FILE, {}) if "lodging" in services else {},
        "car_schema": _load_json(_CAR_SCHEMA_FILE, {}) if "car" in services else {},
        "inventory_status": {"lodging": "provider_pending", "car": "provider_pending"},
    })
