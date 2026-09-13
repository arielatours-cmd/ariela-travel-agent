import json
import os
from pathlib import Path

import requests
from flask import Blueprint, jsonify, request

travel_agents = Blueprint("travel_agents", __name__)

_DATA_FILE = Path(__file__).resolve().parent / "data" / "attractions.json"

TINKERBELL_SYSTEM = """את טינקרבל, סוכנת הנסיעות הראשית של ARIELA AI TRAVEL.
את מנהלת שיחה טבעית וחופשית בעברית (או בשפת הלקוח), כמו סוכנת נסיעות אנושית מצוינת.
המטרה שלך היא להבין מה הלקוח באמת מחפש, בלי להקריא שאלון ובלי לשאול שוב מידע שכבר נאמר.
שאלי בכל פעם רק את השאלה החשובה הבאה. אפשר להתייחס גם להעדפות רכות: טבע, ערים, חופים, שופינג, ילדים, תינוקות, נגישות, קצב, חיי לילה, קזינו, אקסטרים, אוכל, רכב ומרחקי נסיעה.
לעולם אל תמציאי מחיר טיסה, זמינות או דיל. טיסות אמיתיות הן באחריות אריאלה ומנוע הסריקות.
החזירי JSON בלבד עם המפתחות reply, profile, ready_for_flights, ready_for_travel.
profile הוא אובייקט מצטבר. אל תמחקי מידע קודם אלא אם הלקוח תיקן אותו.
שדות אפשריים: destination_mode, destinations, departure_airports, date_mode, departure_date, return_date, outbound_month, return_month, date_flex_days, adults, children, child_ages, infants, budget_mode, budget_amount, flight_preference, baggage, vacation_styles, nature, urban, shopping, nightlife, casino, accessibility, baby_friendly, pace, max_drive_minutes, notes.
ready_for_flights=true רק כשיש מספיק מידע מעשי לחיפוש טיסה: יעד/כיוון יעד, תקופה, נוסעים. ready_for_travel=true כשיש יעד והעדפות שמאפשרים התאמת אטרקציות.
"""


def _call_tinkerbell(message, history, profile):
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    model = os.getenv("TINKERBELL_MODEL", "gpt-5.6-luna")
    conversation = []
    for item in (history or [])[-12:]:
        role = "assistant" if item.get("role") == "assistant" else "user"
        conversation.append({"role": role, "content": str(item.get("content") or "")[:2500]})
    conversation.append({"role": "user", "content": message})
    payload = {
        "model": model,
        "instructions": TINKERBELL_SYSTEM + "\nפרופיל שכבר נאסף:\n" + json.dumps(profile or {}, ensure_ascii=False),
        "input": conversation,
        "text": {"format": {"type": "json_object"}},
        "max_output_tokens": 1200,
    }
    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=payload,
        timeout=35,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Tinkerbell API error {response.status_code}")
    body = response.json()
    text = body.get("output_text")
    if not text:
        chunks = []
        for out in body.get("output") or []:
            for part in out.get("content") or []:
                if part.get("type") == "output_text":
                    chunks.append(part.get("text") or "")
        text = "".join(chunks)
    result = json.loads(text or "{}")
    if not isinstance(result.get("profile"), dict):
        result["profile"] = dict(profile or {})
    return result


def _truthy(value):
    return str(value or "").strip().lower() in {"כן", "yes", "true", "1", "חלקית"}


def _load_attractions():
    try:
        data = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
        return data.get("attractions", data if isinstance(data, list) else [])
    except Exception:
        return []


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
            (profile.get("nature") or "טבע" in styles, "טבע ונופים", "טבע ונופים"),
            (profile.get("urban") or "עירוני" in styles, "טיול עירוני", "טיול עירוני"),
            (profile.get("shopping") or "שופינג" in styles, "שופינג", "שופינג"),
            (profile.get("nightlife") or "חיי לילה" in styles, "ברים/מועדונים/מסיבות", "חיי לילה"),
            (profile.get("casino"), "קזינו", "קזינו"),
            (profile.get("baby_friendly") or int(profile.get("infants") or 0) > 0, "מתאים לתינוקות", "מתאים לתינוקות"),
            (int(profile.get("children") or 0) > 0, "מתאים לילדים", "מתאים לילדים"),
        ]
        for wanted, field, label in checks:
            if wanted and _truthy(row.get(field)):
                score += 3
                reasons.append(label)
            elif wanted and str(row.get(field) or "").strip() == "לא":
                score -= 4
        if profile.get("accessibility") and str(row.get("נגישות") or "") in {"כן", "חלקית"}:
            score += 4; reasons.append("נגישות")
        rows.append((score, row, reasons))
    rows.sort(key=lambda x: x[0], reverse=True)
    out = []
    for score, row, reasons in rows[:limit]:
        out.append({
            "name": row.get("שם האטרקציה"), "country": row.get("מדינה"),
            "region": row.get("אזור/מחוז"), "city": row.get("עיר/בסיס"),
            "type": row.get("סוג ראשי"), "score": score, "reasons": reasons,
            "duration": row.get("משך מומלץ"), "difficulty": row.get("רמת קושי"),
            "accessibility": row.get("נגישות"), "price": row.get("מחיר/הערת מחיר"),
            "official_url": row.get("אתר רשמי"), "booking_url": row.get("קישור הזמנה/כרטיסים"),
            "notes": row.get("הערות"),
        })
    return out


def _ariella_handoff(profile):
    return {
        "destination_mode": profile.get("destination_mode") or ("specific" if profile.get("destinations") else "open"),
        "destinations": profile.get("destinations") or [],
        "departure_airports": profile.get("departure_airports") or [],
        "date_mode": profile.get("date_mode"),
        "departure_date": profile.get("departure_date"),
        "return_date": profile.get("return_date"),
        "outbound_month": profile.get("outbound_month"),
        "return_month": profile.get("return_month"),
        "date_flex_days": profile.get("date_flex_days") or 0,
        "adults": profile.get("adults"), "children": profile.get("children") or 0,
        "budget_mode": profile.get("budget_mode"), "budget_amount": profile.get("budget_amount"),
        "flight_preference": profile.get("flight_preference"), "baggage": profile.get("baggage"),
    }


@travel_agents.post("/api/tinkerbell/chat")
def tinkerbell_chat():
    body = request.get_json(silent=True) or {}
    message = str(body.get("message") or "").strip()
    if not message:
        return jsonify({"status": "error", "message": "message is required"}), 400
    profile = body.get("profile") if isinstance(body.get("profile"), dict) else {}
    history = body.get("history") if isinstance(body.get("history"), list) else []
    try:
        result = _call_tinkerbell(message, history, profile)
    except Exception as exc:
        return jsonify({"status": "error", "message": "טינקרבל לא זמינה כרגע.", "detail": str(exc)}), 503
    merged = dict(profile)
    merged.update({k: v for k, v in result.get("profile", {}).items() if v not in (None, "", [])})
    travel = _travel_matches(merged) if result.get("ready_for_travel") else []
    return jsonify({
        "status": "success", "agent": "Tinkerbell", "reply": result.get("reply") or "ספרו לי עוד קצת על החופשה שאתם מחפשים.",
        "profile": merged, "ready_for_flights": bool(result.get("ready_for_flights")),
        "ariella_handoff": _ariella_handoff(merged), "ready_for_travel": bool(result.get("ready_for_travel")),
        "travel_agent": {"agent": "Travel", "attractions": travel},
    })
