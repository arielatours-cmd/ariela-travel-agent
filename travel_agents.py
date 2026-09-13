import json
import os
from datetime import date
from pathlib import Path

import requests
from flask import Blueprint, jsonify, request

travel_agents = Blueprint("travel_agents", __name__)

_DATA_FILE = Path(__file__).resolve().parent / "data" / "attractions.json"

ARIELLA_SYSTEM = """את אריאלה, סוכנת הנסיעות הראשית והיחידה שמדברת עם הלקוח של ARIELA AI TRAVEL.
את מנהלת שיחה טבעית וקצרה בעברית (או בשפת הלקוח).
תפקידך לשמור בשקט את הנתונים במבנה החיפוש. אסור לחזור על מידע שהלקוח כבר מסר, אסור לסכם אותו ואסור לכתוב מה את יכולה לעשות או מה תעשי בעתיד.
אסור לכתוב ניסוחים כמו: "אבדוק", "אני מתחילה לבדוק", "אפשר לבדוק", "אני יכולה לעזור", "אחפש", "מעולה, מתחילה" וכדומה.
אם חסר מידע לחיפוש טיסה, שאלי רק את השאלה החסרה הבאה. אם המידע מלא, אל תכריזי שהחיפוש התחיל ואל תמציאי תוצאות.
החזירי JSON בלבד עם המפתחות reply, profile, ready_for_travel.
profile הוא אובייקט מצטבר. אל תמחקי מידע קודם אלא אם הלקוח תיקן אותו.
שדות אפשריים: destination_mode, destinations, departure_airports, date_mode, departure_date, return_date, outbound_month, return_month, date_flex_days, adults, children, child_ages, infants, budget_mode, budget_amount, flight_preference, baggage, vacation_styles, nature, urban, shopping, nightlife, casino, accessibility, baby_friendly, pace, max_drive_minutes, notes.
"""

TINKERBELL_SYSTEM = """את טינקרבל, סוכנת פנימית של ARIELA AI TRAVEL. אינך מדברת עם הלקוח.
התפקיד שלך הוא לפרש ניסוחים חופשיים, שגיאות כתיב וביטויים עמומים ולהמיר רק מידע שנאמר בפועל לשדות מובנים עבור אריאלה.
שמרי כל פרט שאפשר למפות ל-profile כדי שאריאלה לא תצטרך לשאול עליו שוב.
אם הלקוח אומר שאין תקציב/אין הגבלת תקציב/לא מוגבל בתקציב/המחיר לא משנה, מפִי ל-budget_mode=unlimited.
כאשר נמסרים יום וחודש ללא שנה, השתמשי בתאריך הנוכחי: אם החודש כבר עבר השנה, השנה היא הבאה; אם הוא עדיין לפנינו, השנה היא הנוכחית. צרי departure_date/return_date מלאים ואל תבקשי שנה כשאפשר להסיק אותה.
אל תנחשי פרטים שלא נאמרו. אם משהו לא ברור, כתבי אותו ב-unclear.
החזירי JSON בלבד: profile_patch כאובייקט, interpretation כמחרוזת קצרה לשימוש פנימי, unclear כמערך מחרוזות.
"""


def _openai_json(key, model, developer_text, conversation, max_output_tokens=1200):
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
    p = dict(profile or {})
    p["current_date"] = date.today().isoformat()
    developer = TINKERBELL_SYSTEM + "\nפרופיל קיים:\n" + json.dumps(p, ensure_ascii=False)
    result = _openai_json(key, model, developer, _conversation(history, message), max_output_tokens=650)
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
        "tinkerbell_interpretation": tinkerbell.get("interpretation") or "",
        "tinkerbell_unclear": tinkerbell.get("unclear") or [],
    }
    developer = ARIELLA_SYSTEM + "\nמידע פנימי שאסור לחשוף ללקוח:\n" + json.dumps(internal, ensure_ascii=False)
    result = _openai_json(key, model, developer, _conversation(history, message), max_output_tokens=900)
    if not isinstance(result.get("profile"), dict):
        result["profile"] = dict(profile or {})
    return result


def _has_destination(profile):
    return bool(profile.get("destinations")) or profile.get("destination_mode") in {"open", "ariella", "flexible"}


def _has_dates(profile):
    return bool(
        (profile.get("departure_date") and profile.get("return_date"))
        or profile.get("outbound_month")
    )


def _has_travelers(profile):
    adults = profile.get("adults")
    return adults is not None and str(adults) != "" and int(adults or 0) > 0


def _has_budget(profile):
    return bool(profile.get("budget_mode") or profile.get("budget_amount") not in (None, ""))


def _missing_flight_question(profile):
    if not _has_destination(profile):
        return "לאן תרצו לטוס? אם אין יעד מסוים, אפשר לכתוב שאתם פתוחים להצעות."
    if not _has_dates(profile):
        return "מתי תרצו לטוס? אפשר לכתוב תאריכים מדויקים או חודש מועדף."
    if not _has_travelers(profile):
        return "כמה נוסעים יהיו, וכמה מהם ילדים או תינוקות?"
    if not _has_budget(profile):
        return "מה התקציב המשוער לחופשה? אם אין מגבלת תקציב, אפשר לכתוב שאין הגבלה."
    if not profile.get("departure_airports"):
        return "מאיזה שדה תעופה תרצו לצאת?"
    if not profile.get("flight_preference"):
        return "חשוב לכם לטוס ישיר, או שגם קונקשן מתאים?"
    if not profile.get("baggage"):
        return "איזו כבודה תרצו לכלול — תיק יד, טרולי או מזוודה?"
    return ""


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
            score += 4
            reasons.append("נגישות")
        rows.append((score, row, reasons))
    rows.sort(key=lambda x: x[0], reverse=True)
    out = []
    for score, row, reasons in rows[:limit]:
        out.append({
            "name": row.get("שם האטרקציה"),
            "country": row.get("מדינה"),
            "region": row.get("אזור/מחוז"),
            "city": row.get("עיר/בסיס"),
            "type": row.get("סוג ראשי"),
            "score": score,
            "reasons": reasons,
            "duration": row.get("משך מומלץ"),
            "difficulty": row.get("רמת קושי"),
            "accessibility": row.get("נגישות"),
            "price": row.get("מחיר/הערת מחיר"),
            "official_url": row.get("אתר רשמי"),
            "booking_url": row.get("קישור הזמנה/כרטיסים"),
            "notes": row.get("הערות"),
        })
    return out


def _tinkerbell_handoff(profile):
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
        "adults": profile.get("adults"),
        "children": profile.get("children") or 0,
        "budget_mode": profile.get("budget_mode"),
        "budget_amount": profile.get("budget_amount"),
        "flight_preference": profile.get("flight_preference"),
        "baggage": profile.get("baggage"),
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
        result = _call_ariella(message, history, normalized, tinkerbell)
    except Exception as exc:
        return jsonify({"status": "error", "message": "אריאלה לא זמינה כרגע.", "detail": str(exc)}), 503

    merged = dict(normalized)
    merged.update({k: v for k, v in result.get("profile", {}).items() if v not in (None, "", [])})

    next_question = _missing_flight_question(merged)
    intake_complete = not bool(next_question)
    ready_for_flights = intake_complete
    travel = _travel_matches(merged) if intake_complete and _has_destination(merged) else []

    return jsonify({
        "status": "success",
        "agent": "Ariella",
        "reply": next_question,
        "profile": merged,
        "ready_for_flights": ready_for_flights,
        "flight_search_started": False,
        "ready_for_travel": bool(travel),
        "intake_complete": intake_complete,
        "show_assistance": intake_complete,
        "tinkerbell_handoff": _tinkerbell_handoff(merged),
        "travel_agent": {"agent": "Travel", "attractions": travel},
    })
