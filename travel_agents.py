import json
import os
import re
import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path

import requests
from flask import Blueprint, jsonify, request, session

from config import DB_PATH
from database import utc_now_iso
from lodging_providers import lodging_inventory_status
from scanner import run_customer_trip_search

travel_agents = Blueprint("travel_agents", __name__)

_DATA_DIR = Path(__file__).resolve().parent / "data"
_ATTRACTION_FILES = [_DATA_DIR / "attractions.json", _DATA_DIR / "attractions_global30.json"]
_LODGING_SCHEMA_FILE = _DATA_DIR / "lodging_preferences.json"
_CAR_SCHEMA_FILE = _DATA_DIR / "car_preferences.json"
_AIRPORTS_FILE = Path(__file__).resolve().parent / "static" / "airports.json"

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
החזירי JSON בלבד עם המפתחות reply ו-profile. profile מצטבר ואסור למחוק מידע קודם אלא אם הלקוח תיקן אותו.
שדות עיקריים: vacation_type, services, destination_mode, destinations, departure_airports, date_mode, departure_date, return_date, outbound_month, return_month, date_flex_days, adults, children, child_ages, infants, travel_party_type, save_traveler_names, traveler_names, budget_mode, budget_amount, flight_preference, baggage, vacation_styles, accessibility, pace, max_drive_minutes, lodging_type, rooms, bathrooms, hotel_rooms, beds, lodging_budget_mode, lodging_budget_amount, location_priority, lodging_amenities, meal_plan, star_rating, cancellation, pickup_location, dropoff_location, driver_age, car_type, passenger_capacity, large_bags, transmission, car_budget_mode, car_budget_amount, car_features, fuel_policy, one_way, notes.
אם הלקוח מציין בן/בת זוג, משפחה, ילדים או חברים, שמרי travel_party_type מתאים. שמות נוסעים נשמרים רק אם הלקוח בוחר במפורש לשמור אותם.
"""

TINKERBELL_SYSTEM = """את טינקרבל, סוכנת פנימית. אינך מדברת עם הלקוח.
פרשי ניסוח חופשי ושגיאות כתיב ומפי רק מידע שנאמר בפועל לשדות profile.
מטרת נסיעה: עסקים=>business; סקי=>ski; טיול/חופשה בחו"ל=>standard.
שירותים: טיסה/טיסות=>flight; מלון/דירה/וילה/לינה=>lodging; אטרקציות=>attractions; מסלול/תכנון טיול=>route; רכב/השכרת רכב=>car.
'אין תקציב'/'בלי הגבלת תקציב'/'לא משנה המחיר' => budget_mode=unlimited; ובהקשר לינה או רכב השתמשי בשדה התקציב המתאים.
כאשר נמסרים יום וחודש ללא שנה, הסיקי את השנה העתידית הקרובה לפי current_date וצרי תאריכים מלאים.
אל תנחשי מידע שלא נאמר. החזירי JSON בלבד: profile_patch, interpretation, unclear.
"""


def _db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema():
    with _db() as conn:
        member_cols = {r["name"] for r in conn.execute("PRAGMA table_info(members)").fetchall()}
        if "gender" not in member_cols:
            conn.execute("ALTER TABLE members ADD COLUMN gender TEXT")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS ariella_travel_companions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id INTEGER NOT NULL,
                first_name TEXT NOT NULL,
                relationship TEXT,
                created_at TEXT NOT NULL,
                last_travelled_at TEXT,
                UNIQUE(member_id, first_name),
                FOREIGN KEY(member_id) REFERENCES members(id)
            );
            CREATE TABLE IF NOT EXISTS ariella_trip_conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id INTEGER NOT NULL,
                trip_id INTEGER NOT NULL,
                history_json TEXT NOT NULL,
                profile_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(member_id) REFERENCES members(id),
                FOREIGN KEY(trip_id) REFERENCES trip_requests(id)
            );
            CREATE INDEX IF NOT EXISTS idx_ariella_companions_member ON ariella_travel_companions(member_id);
            CREATE INDEX IF NOT EXISTS idx_ariella_conversations_trip ON ariella_trip_conversations(trip_id);
        """)
        conn.commit()


def _member_context():
    member_id = session.get("member_id")
    if not member_id:
        return None
    _ensure_schema()
    with _db() as conn:
        row = conn.execute("SELECT id,full_name,gender FROM members WHERE id=?", (member_id,)).fetchone()
        if not row:
            return None
        companions = [dict(x) for x in conn.execute(
            "SELECT first_name,relationship,last_travelled_at FROM ariella_travel_companions WHERE member_id=? ORDER BY id",
            (member_id,),
        ).fetchall()]
    out = dict(row)
    out["companions"] = companions
    return out


def _persist_gender(member_id, gender):
    gender = str(gender or "").strip().lower()
    if gender not in {"male", "female"}:
        return
    _ensure_schema()
    with _db() as conn:
        conn.execute("UPDATE members SET gender=? WHERE id=?", (gender, member_id))
        conn.commit()


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
            "hotel": "lodging", "hotels": "lodging", "לינה": "lodging", "מלון": "lodging", "דירה": "lodging", "וילה": "lodging",
            "attraction": "attractions", "אטרקציה": "attractions", "אטרקציות": "attractions", "אתר סקי": "attractions",
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
    party = str(p.get("travel_party_type") or "").lower()
    if party in {"family", "friends", "couple", "משפחה", "חברים", "זוג"} and p.get("save_traveler_names") is None:
        return "רוצים לשתף את השמות הפרטיים של מי שנוסע איתכם כדי שאזכור אותם לחיפושים הבאים?"
    if p.get("save_traveler_names") is True and not p.get("traveler_names"):
        return "כתבו את השמות הפרטיים של הנוסעים שתרצו שאזכור."
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
        return "מה הכי חשוב במיקום?"
    if p.get("lodging_amenities") in (None, "", []):
        return "מה חשוב שיהיה במקום?"
    return ""


def _car_question(p):
    if not p.get("pickup_location"):
        return "איפה תרצו לאסוף את הרכב?"
    if not p.get("dropoff_location"):
        return "איפה תרצו להחזיר את הרכב?"
    if not p.get("driver_age"):
        return "מה גיל הנהג הראשי?"
    if not p.get("car_type"):
        return "איזה רכב מתאים לכם?"
    if not p.get("transmission"):
        return "חשוב לכם רכב אוטומטי, או שלא משנה?"
    if not _has_budget(p, "car_"):
        return "יש מגבלת תקציב לרכב — ליום או לכל התקופה?"
    if p.get("car_features") in (None, "", []):
        return "יש משהו שחייב להיות ברכב?"
    return ""


def _experience_question(p):
    if p.get("vacation_styles") in (None, "", []):
        return "מה תרצו לשלב בחופשה?"
    if "route" in _normalize_services(p.get("services")) and not p.get("pace"):
        return "איזה קצב מתאים לכם — רגוע, בינוני או עמוס?"
    return ""


def _next_question(p):
    if not p.get("vacation_type"):
        return "", "purpose"
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
    return "", "confirm"


def _simple_number(message):
    match = re.fullmatch(r"\s*(\d{1,3})\s*", str(message or ""))
    if not match:
        return None
    value = int(match.group(1))
    return value if value > 0 else None


def _contextual_patch(message, profile):
    p = dict(profile or {})
    services = _normalize_services(p.get("services"))
    number = _simple_number(message)
    text = str(message or "").strip().lower()
    no_special = text in {"לא", "אין", "לא חשוב", "לא משנה", "בלי", "ללא", "none", "no"}
    yes = text in {"כן", "כן בבקשה", "yes", "y"}
    if p.get("travel_party_type") and p.get("save_traveler_names") is None:
        if yes:
            return {"save_traveler_names": True}
        if no_special:
            return {"save_traveler_names": False}
    if "lodging" in services:
        lodging_type = str(p.get("lodging_type") or "")
        if lodging_type in {"apartment", "villa", "דירה", "וילה"}:
            if not p.get("rooms") and number:
                return {"rooms": number}
            if p.get("rooms") and not p.get("bathrooms") and number:
                return {"bathrooms": number}
        if lodging_type in {"hotel", "resort", "מלון", "ריזורט"} and not p.get("hotel_rooms") and number:
            return {"hotel_rooms": number}
        if lodging_type and not _has_budget(p, "lodging_") and no_special:
            return {"lodging_budget_mode": "unlimited"}
        if _has_budget(p, "lodging_") and p.get("location_priority") not in (None, "", []) and p.get("lodging_amenities") in (None, "", []) and no_special:
            return {"lodging_amenities": ["none"]}
    if "car" in services:
        if p.get("pickup_location") and p.get("dropoff_location") and not p.get("driver_age") and number:
            return {"driver_age": number}
        if p.get("car_type") and p.get("transmission") and not _has_budget(p, "car_") and no_special:
            return {"car_budget_mode": "unlimited"}
        if _has_budget(p, "car_") and p.get("car_features") in (None, "", []) and no_special:
            return {"car_features": ["none"]}
    return {}


def _load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _load_attractions():
    combined, seen = [], set()
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


def _travel_matches(profile, limit=10):
    raw_dest = profile.get("destinations") or []
    if isinstance(raw_dest, str):
        raw_dest = [raw_dest]
    destinations = [str(x).lower() for x in raw_dest]
    styles = {str(x).lower() for x in (profile.get("vacation_styles") or [])}
    rows = []
    for row in _load_attractions():
        country = str(row.get("מדינה") or "").lower()
        city = str(row.get("עיר/בסיס") or "").lower()
        if destinations and not any(d in country or d in city or country in d or city in d for d in destinations):
            continue
        score, reasons = 0, []
        checks = [
            ("טבע" in styles, "טבע ונופים", "טבע"),
            ("ערים" in styles or "עירוני" in styles, "טיול עירוני", "עירוני"),
            ("שופינג" in styles, "שופינג", "שופינג"),
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


def _trip_days(profile):
    try:
        if profile.get("departure_date") and profile.get("return_date"):
            a = datetime.strptime(profile["departure_date"], "%Y-%m-%d").date()
            b = datetime.strptime(profile["return_date"], "%Y-%m-%d").date()
            return max(1, (b - a).days + 1)
    except Exception:
        pass
    return 7


def _recommended_itinerary(profile, attractions):
    if "route" not in _normalize_services(profile.get("services")):
        return []
    days = _trip_days(profile)
    picks = list(attractions or [])
    if not picks:
        return []
    plan = []
    for day_num in range(1, days + 1):
        item = picks[(day_num - 1) % len(picks)]
        plan.append({
            "day": day_num,
            "base": item.get("city") or item.get("region") or item.get("country"),
            "activity": item.get("name"),
            "price": item.get("price"),
            "booking_url": item.get("booking_url") or item.get("official_url"),
            "suggested_nights": 1,
        })
    return plan


def _load_airports():
    data = _load_json(_AIRPORTS_FILE, [])
    return data if isinstance(data, list) else []


def _airport_options(profile):
    raw = profile.get("destinations") or []
    if isinstance(raw, str):
        raw = [raw]
    needles = [str(x).strip().lower() for x in raw if str(x).strip()]
    matches = []
    for a in _load_airports():
        hay = " ".join(str(a.get(k) or "") for k in ("country_he", "country_en", "city_he", "city_en")).lower()
        if needles and not any(n in hay or hay in n for n in needles):
            continue
        matches.append({"value": a.get("code"), "label": f"{a.get('city_he') or a.get('city_en')} — {a.get('code')}"})
    return matches[:12]


def _ui_choice(stage, question, profile):
    if stage == "shared" and "השמות הפרטיים" in question:
        return {"field": "save_traveler_names", "type": "single", "title": question, "options": [{"value": True, "label": "כן"}, {"value": False, "label": "לא"}]}
    if stage == "lodging" and question == "מה הכי חשוב במיקום?":
        return {"field": "location_priority", "type": "multi", "title": "מה חשוב לכם במיקום?", "options": [{"value": x, "label": x} for x in ["שקט", "חניה", "מרכז", "חוף", "תחבורה", "אטרקציות"]]}
    if stage == "lodging" and question == "מה חשוב שיהיה במקום?":
        return {"field": "lodging_amenities", "type": "multi", "title": "מה חשוב שיהיה במקום?", "options": [{"value": x, "label": x} for x in ["בריכה", "חניה", "מטבח", "מכונת כביסה", "מעלית", "ארוחת בוקר", "נגישות", "מרפסת"]]}
    if stage == "car" and question in {"איפה תרצו לאסוף את הרכב?", "איפה תרצו להחזיר את הרכב?"}:
        airports = _airport_options(profile)
        if airports:
            field = "pickup_location" if "לאסוף" in question else "dropoff_location"
            if field == "dropoff_location" and profile.get("pickup_location"):
                airports = [{"value": profile.get("pickup_location"), "label": "אותו מקום כמו האיסוף"}] + airports
            return {"field": field, "type": "single", "title": question, "options": airports}
    if stage == "car" and question == "איזה רכב מתאים לכם?":
        return {"field": "car_type", "type": "single", "title": question, "options": [{"value": x, "label": x} for x in ["קטן", "משפחתי", "SUV", "7 מקומות", "לא משנה"]]}
    if stage == "car" and question == "חשוב לכם רכב אוטומטי, או שלא משנה?":
        return {"field": "transmission", "type": "single", "title": question, "options": [{"value": "automatic", "label": "אוטומטי"}, {"value": "any", "label": "לא משנה"}]}
    if stage == "car" and question == "יש משהו שחייב להיות ברכב?":
        return {"field": "car_features", "type": "multi", "title": question, "allow_none": True, "options": [{"value": x, "label": x} for x in ["מושב תינוק", "בוסטר", "נהג נוסף", "ביטוח מלא", "תא מטען גדול", "קילומטרים ללא הגבלה"]]}
    if stage == "experience" and question == "מה תרצו לשלב בחופשה?":
        return {"field": "vacation_styles", "type": "multi", "title": "מה מעניין אתכם? אפשר לבחור כמה:", "options": [{"value": x, "label": x} for x in ["טבע", "ערים", "חופים", "שופינג", "חיי לילה", "אקסטרים", "תרבות ומוזיאונים", "אוכל וקולינריה", "אטרקציות לילדים", "ספא ורוגע"]]}
    return None


def _flight_handoff(p):
    return {
        "destination_mode": p.get("destination_mode") or ("specific" if p.get("destinations") else "open"),
        "destinations": p.get("destinations") or [], "departure_airports": p.get("departure_airports") or [],
        "date_mode": p.get("date_mode"), "departure_date": p.get("departure_date"), "return_date": p.get("return_date"),
        "outbound_month": p.get("outbound_month"), "return_month": p.get("return_month"), "date_flex_days": p.get("date_flex_days") or 0,
        "adults": p.get("adults"), "children": p.get("children") or 0, "budget_mode": p.get("budget_mode"),
        "budget_amount": p.get("budget_amount"), "flight_preference": p.get("flight_preference"), "baggage": p.get("baggage"),
    }


def _scanner_answers(profile):
    raw_dest = profile.get("destinations") or []
    if isinstance(raw_dest, list):
        destinations = ",".join(str(x) for x in raw_dest)
    else:
        destinations = str(raw_dest)
    vacation_type = str(profile.get("vacation_type") or "standard")
    if vacation_type not in {"standard", "ski", "business"}:
        vacation_type = "standard"
    return {
        "vacation_type": vacation_type,
        "destination_mode": profile.get("destination_mode") or ("specific" if destinations else "open"),
        "destinations": destinations,
        "origin_airports": profile.get("departure_airports") or [],
        "date_mode": profile.get("date_mode") or ("exact" if profile.get("departure_date") else "month"),
        "departure_date": profile.get("departure_date"), "return_date": profile.get("return_date"),
        "outbound_month": profile.get("outbound_month"), "return_month": profile.get("return_month"),
        "date_flex_days": profile.get("date_flex_days") or 0,
        "adults": profile.get("adults") or 1, "children": profile.get("children") or 0,
        "budget_mode": profile.get("budget_mode"), "budget_amount": profile.get("budget_amount"),
        "flight_preference": profile.get("flight_preference"), "baggage": profile.get("baggage"),
        "services": _normalize_services(profile.get("services")),
    }


def _save_companions(member_id, profile):
    if profile.get("save_traveler_names") is not True:
        return
    names = profile.get("traveler_names") or []
    if isinstance(names, str):
        names = [x.strip() for x in re.split(r"[,;/]+", names) if x.strip()]
    rel = str(profile.get("travel_party_type") or "").strip() or None
    with _db() as conn:
        for name in names:
            first = str(name).strip().split()[0][:80]
            if not first:
                continue
            conn.execute("""
                INSERT INTO ariella_travel_companions(member_id,first_name,relationship,created_at,last_travelled_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(member_id,first_name) DO UPDATE SET relationship=COALESCE(excluded.relationship,relationship),last_travelled_at=excluded.last_travelled_at
            """, (member_id, first, rel, utc_now_iso(), utc_now_iso()))
        conn.commit()


def _start_scan(trip_id, answers):
    """Start a customer scan and persist failures so the waiting page cannot hang silently."""
    def worker():
        try:
            result = run_customer_trip_search(trip_id, answers)
            status = str((result or {}).get("status") or "unknown")
            with _db() as conn:
                row = conn.execute("SELECT answers_json FROM trip_requests WHERE id=?", (trip_id,)).fetchone()
                saved = json.loads(row["answers_json"] or "{}") if row else {}
                saved["_flight_search_result"] = result or {}
                saved["_flight_search_finished"] = True
                conn.execute("UPDATE trip_requests SET answers_json=? WHERE id=?", (json.dumps(saved, ensure_ascii=False), trip_id))
                conn.commit()
        except Exception as exc:
            with _db() as conn:
                row = conn.execute("SELECT answers_json FROM trip_requests WHERE id=?", (trip_id,)).fetchone()
                saved = json.loads(row["answers_json"] or "{}") if row else {}
                saved["_flight_search_finished"] = True
                saved["_flight_search_result"] = {"status":"error","message":str(exc)[:500]}
                conn.execute("UPDATE trip_requests SET answers_json=? WHERE id=?", (json.dumps(saved, ensure_ascii=False), trip_id))
                conn.commit()
    threading.Thread(target=worker, daemon=True, name=f"ariella-trip-{trip_id}").start()


# NOTE (route removed): this legacy chat engine used to be bound to
# POST /api/ariella/chat, colliding with the current engine registered in
# ariella_chat_v2.py -> ariella_chat_clean.py. Blueprint registration order
# made THIS legacy handler win, so the live chat widget was silently talking
# to the old engine instead of chat_clean(). The route is removed so
# /api/ariella/chat is served only by the current, live code
# (ariella_chat_clean.chat_clean). This function is kept, unrouted, until
# it is reviewed and either merged into the live engine or deleted.
def _legacy_ariella_chat_unused():
    body = request.get_json(silent=True) or {}
    message = str(body.get("message") or "").strip()
    if not message:
        return jsonify({"status": "error", "message": "message is required"}), 400
    profile = body.get("profile") if isinstance(body.get("profile"), dict) else {}
    history = body.get("history") if isinstance(body.get("history"), list) else []
    member = _member_context()
    if member:
        if member.get("gender") and not profile.get("customer_gender"):
            profile["customer_gender"] = member.get("gender")
        profile["known_companions"] = member.get("companions") or []
        if profile.get("customer_gender"):
            _persist_gender(member["id"], profile.get("customer_gender"))
    try:
        deterministic = _contextual_patch(message, profile)
        base_profile = dict(profile)
        base_profile.update(deterministic)
        tinkerbell = _call_tinkerbell(message, history, base_profile)
        normalized = dict(base_profile)
        normalized.update({k: v for k, v in tinkerbell.get("profile_patch", {}).items() if v not in (None, "", [])})
        normalized["services"] = _normalize_services(normalized.get("services"))
        if normalized.get("vacation_type") and "flight" not in normalized["services"] and normalized["services"]:
            normalized["services"].insert(0, "flight")
        result = _call_ariella(message, history, normalized, tinkerbell)
    except Exception as exc:
        return jsonify({"status": "error", "message": "אריאלה לא זמינה כרגע.", "detail": str(exc)}), 503
    merged = dict(normalized)
    merged.update({k: v for k, v in result.get("profile", {}).items() if v not in (None, "", [])})
    merged["services"] = _normalize_services(merged.get("services"))
    if merged.get("vacation_type") and merged["services"] and "flight" not in merged["services"]:
        merged["services"].insert(0, "flight")
    next_question, stage = _next_question(merged)
    complete = stage == "confirm"
    services = merged.get("services") or []
    travel = _travel_matches(merged) if complete and ("attractions" in services or "route" in services) else []
    lodging_status = lodging_inventory_status() if "lodging" in services else {"providers": [], "live_provider_count": 0, "live_inventory_available": False}
    return jsonify({
        "status": "success", "agent": "Ariella", "reply": next_question, "profile": merged,
        "stage": stage, "show_purpose_picker": stage == "purpose", "show_service_picker": stage == "services",
        "ui_choice": _ui_choice(stage, next_question, merged), "services": services,
        "ready_for_flights": complete and "flight" in services, "flight_search_started": False,
        "ready_for_lodging": complete and "lodging" in services, "ready_for_car": complete and "car" in services,
        "ready_for_travel": bool(travel), "intake_complete": complete, "requires_confirmation": complete,
        "confirmation_text": "עברו על כל הפרטים ב'החופשה שלי'. אם הכול נכון, אשרו יציאה לחיפוש.",
        "tinkerbell_handoff": _flight_handoff(merged), "travel_agent": {"attractions": travel},
        "lodging_schema": _load_json(_LODGING_SCHEMA_FILE, {}) if "lodging" in services else {},
        "car_schema": _load_json(_CAR_SCHEMA_FILE, {}) if "car" in services else {},
        "inventory_status": {"lodging": lodging_status, "car": "provider_pending"},
    })


def _clean_state_to_profile(state):
    """Translate the natural-chat state into the existing flight scanner contract."""
    state = state or {}
    travelers = state.get("travelers") or {}
    destination = state.get("destination") or {}
    dates = state.get("dates") or {}
    budget = state.get("budget_per_person") or {}
    flight = state.get("flight") or {}
    places = destination.get("places") or []
    if isinstance(places, str):
        places = [places]

    # Scanner inventory is keyed by IATA. Resolve natural city/country names
    # against Ariella's airport catalogue, while preserving explicit IATA codes.
    destination_codes = []
    unresolved_destinations = []
    airports = _load_airports()
    for place in places:
        raw = str(place or "").strip()
        if len(raw) == 3 and raw.isalpha():
            destination_codes.append(raw.upper())
            continue
        needle = raw.lower()
        matches = []
        for airport in airports:
            hay = " ".join(str(airport.get(k) or "") for k in ("country_he","country_en","city_he","city_en")).lower()
            if needle and needle in hay:
                code = str(airport.get("code") or "").upper()
                if code:
                    matches.append(code)
        destination_codes.extend(matches[:4])
        if not matches and raw:
            unresolved_destinations.append(raw)
    destination_codes = list(dict.fromkeys(destination_codes))

    requested = state.get("requested_services") or []
    services = ["flight"] if "flights" in requested or not requested else []
    if "lodging" in requested: services.append("lodging")
    if "car" in requested: services.append("car")
    if "trip_planning" in requested: services.extend(["route","attractions"])

    dep = dates.get("departure")
    ret = dates.get("return")
    period = str(dates.get("period") or "")
    profile = {
        "vacation_type": state.get("trip_type") or "standard",
        "services": list(dict.fromkeys(services)),
        "destination_mode": destination.get("mode") or ("specific" if destination_codes else "open"),
        "destinations": destination_codes,
        "destination_names": [str(x).strip() for x in places if str(x).strip()],
        "unresolved_destinations": unresolved_destinations,
        "departure_airports": [state.get("departure_airport") or "TLV"],
        "date_mode": "exact" if dep and ret else ("month" if period else "anytime"),
        "departure_date": dep,
        "return_date": ret,
        "outbound_month": period[:7] if len(period) >= 7 else None,
        "return_month": period[:7] if len(period) >= 7 else None,
        "date_flex_days": dates.get("flexibility_days") or 0,
        "adults": travelers.get("adults") or 1,
        "children": travelers.get("children") or 0,
        "child_ages": travelers.get("child_ages") or [],
        "infants": travelers.get("infants") or 0,
        "budget_mode": "limited" if budget.get("amount") is not None else "unlimited",
        "budget_amount": budget.get("amount"),
        "flight_preference": flight.get("connection_preference"),
        "baggage": flight.get("baggage") or [],
    }
    return profile


@travel_agents.post("/api/ariella/confirm-clean-search")
def confirm_clean_search():
    """Create the vacation and start the real flight pipeline after chat approval."""
    member = _member_context()
    if not member:
        return jsonify({"status":"error","message":"נדרשת התחברות כדי לשמור את החופשה."}), 401
    body = request.get_json(silent=True) or {}
    state = body.get("trip_state") if isinstance(body.get("trip_state"), dict) else {}
    history = body.get("history") if isinstance(body.get("history"), list) else []
    if not state.get("search_confirmed"):
        return jsonify({"status":"error","message":"החיפוש עדיין לא אושר."}), 400
    if "flights" not in (state.get("requested_services") or []):
        return jsonify({"status":"error","message":"לא התבקש חיפוש טיסות."}), 400

    profile = _clean_state_to_profile(state)
    answers = _scanner_answers(profile)
    destinations = profile.get("destinations") or []
    request_name = " / ".join(destinations[:3]) if destinations else "חופשה חדשה"
    travel_window = ""
    if profile.get("departure_date") and profile.get("return_date"):
        travel_window = f"{profile['departure_date']} – {profile['return_date']}"
    elif profile.get("outbound_month"):
        travel_window = str(profile["outbound_month"])

    _ensure_schema()
    with _db() as conn:
        cur = conn.execute(
            "INSERT INTO trip_requests(member_id,request_name,travel_window,status,answers_json,created_at) VALUES(?,?,?,?,?,?)",
            (member["id"], request_name, travel_window, "active",
             json.dumps({**profile, **answers, "_chat_state": state}, ensure_ascii=False), utc_now_iso()),
        )
        trip_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO ariella_trip_conversations(member_id,trip_id,history_json,profile_json,created_at) VALUES(?,?,?,?,?)",
            (member["id"], trip_id, json.dumps(history, ensure_ascii=False),
             json.dumps(state, ensure_ascii=False), utc_now_iso()),
        )
        conn.commit()
    _start_scan(trip_id, answers)
    return jsonify({
        "status":"success","trip_id":trip_id,"search_started":True,
        "waiting_url":f"/trip/{trip_id}/waiting"
    })


@travel_agents.post("/api/ariella/confirm-search")
def confirm_search():
    member = _member_context()
    if not member:
        return jsonify({"status": "error", "message": "נדרשת התחברות כדי לשמור חופשה."}), 401
    body = request.get_json(silent=True) or {}
    profile = body.get("profile") if isinstance(body.get("profile"), dict) else {}
    history = body.get("history") if isinstance(body.get("history"), list) else []
    _, stage = _next_question(profile)
    if stage != "confirm":
        return jsonify({"status": "error", "message": "חסרים עדיין פרטים לחיפוש."}), 400
    _ensure_schema()
    gender = profile.get("customer_gender") or member.get("gender")
    if gender:
        _persist_gender(member["id"], gender)
    answers = _scanner_answers(profile)
    raw_dest = profile.get("destinations") or []
    if isinstance(raw_dest, list):
        request_name = " / ".join(str(x) for x in raw_dest[:3]) or "חופשה חדשה"
    else:
        request_name = str(raw_dest or "חופשה חדשה")
    travel_window = ""
    if profile.get("departure_date") and profile.get("return_date"):
        travel_window = f"{profile.get('departure_date')} – {profile.get('return_date')}"
    elif profile.get("outbound_month"):
        travel_window = str(profile.get("outbound_month"))
    with _db() as conn:
        cur = conn.execute(
            "INSERT INTO trip_requests(member_id,request_name,travel_window,status,answers_json,created_at) VALUES(?,?,?,?,?,?)",
            (member["id"], request_name, travel_window, "active", json.dumps({**profile, **answers}, ensure_ascii=False), utc_now_iso()),
        )
        trip_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO ariella_trip_conversations(member_id,trip_id,history_json,profile_json,created_at) VALUES(?,?,?,?,?)",
            (member["id"], trip_id, json.dumps(history, ensure_ascii=False), json.dumps(profile, ensure_ascii=False), utc_now_iso()),
        )
        conn.commit()
    _save_companions(member["id"], profile)
    services = _normalize_services(profile.get("services"))
    if "flight" in services:
        _start_scan(trip_id, answers)
    attractions = _travel_matches(profile) if ("attractions" in services or "route" in services) else []
    itinerary = _recommended_itinerary(profile, attractions)
    female = str(gender or "").lower() == "female"
    closing = "חיפוש החופשה יצא לדרך. לחיפוש נוסף את מוזמנת לחזור אליי בכל עת." if female else "חיפוש החופשה יצא לדרך. לחיפוש נוסף אתה מוזמן לחזור אליי בכל עת."
    return jsonify({
        "status": "success", "trip_id": trip_id, "search_started": "flight" in services,
        "message": closing, "attractions": attractions, "itinerary": itinerary,
        "monitoring_offer": {
            "available": True,
            "title": "מעקב אחר טיסות בתשלום",
            "plans": [
                {"plan": "db", "price_ils": 19, "label": "מעקב חודשי מתוך מאגר אריאלה"},
                {"plan": "intensive", "price_ils": 39, "label": "מעקב חודשי כולל סריקות חיצוניות לפי הצורך"},
            ],
        },
        "reset_draft": True,
    })
