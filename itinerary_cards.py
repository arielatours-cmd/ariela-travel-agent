"""Turn an approved day-by-day itinerary (free Hebrew text from the chat)
into structured day cards with one card per attraction for the vacation's
"מסלול ואטרקציות" tab.

Honesty rules (per product owner):
- Descriptions come from the model, but only for places that appear in the
  approved itinerary text - it never adds attractions.
- Prices and ticket/official links come only from Ariella's attraction DB
  (data/attractions*.json). Nothing priced or linked is invented; a place
  that isn't in the DB gets a map link only.
- Images come from Wikipedia's page image for the place, when one exists.
"""
import json
import logging
import os
import re
from urllib.parse import quote_plus

import requests

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
_DB_FILES = ("attractions.json", "attractions_global30.json", "attractions_global30_extra.json", "attractions_malta.json")
_WIKI_API = "https://en.wikipedia.org/w/api.php"
_WIKI_HEADERS = {"User-Agent": "AriellaTravelAgent/1.0 (itinerary cards)"}

_DAY_LINE = re.compile(
    r"(?<![א-ת])יום\s+(?:\d{1,2}(?!\d)|(?:ה?(?:ראשון|שני|שלישי|רביעי|חמישי|שישי|שבת|אחרון)))"
)

_STRUCTURE_PROMPT = """את ממירה מסלול טיול שאושר (טקסט חופשי בעברית) למבנה JSON עבור כרטיסי מסלול.
כללים:
- כלול רק ימים ומקומות שמופיעים בטקסט. אל תוסיפי אטרקציות שלא הוזכרו.
- items הם אטרקציות/מקומות ספציפיים לביקור (אתר, מוזיאון, פארק, שכונה, חוף, מסעדה מומלצת בשמה). לא פעולות כלליות כמו "ארוחת ערב", "מנוחה", "נסיעה".
- description: 1–2 משפטים בעברית - מה המקום ולמה שווה להגיע, בגובה העיניים. בלי מחירים, בלי שעות פתיחה ובלי קישורים.
- name_en: השם המקובל באנגלית של המקום (כפי שיופיע בוויקיפדיה/במפות), או null אם אין שם ספציפי.
- duration: משך ביקור מומלץ קצר (למשל "שעתיים", "חצי יום") או null.
- date: YYYY-MM-DD אם אפשר להסיק מהטקסט או מתאריך היציאה שניתן, אחרת null.
- base: היישוב/האזור שבו ישנים באותו לילה, אם צוין, אחרת null.
החזירי JSON בלבד בפורמט:
{"days":[{"day":1,"date":null,"title":"כותרת קצרה ליום","city":"העיר/האזור העיקרי","base":null,"summary":"משפט אחד על היום","items":[{"name_he":"","name_en":null,"city":"","description":"","duration":null}]}]}"""


def _load_db():
    records = []
    for filename in _DB_FILES:
        try:
            with open(os.path.join(_DATA_DIR, filename), "r", encoding="utf-8") as fh:
                payload = json.load(fh)
            rows = payload.get("attractions", []) if isinstance(payload, dict) else payload
            records.extend(r for r in rows if isinstance(r, dict))
        except Exception:
            logging.exception("Could not load attraction DB file %s", filename)
    return records


def _db_match(records, name_en, name_he):
    name_en = str(name_en or "").strip().casefold()
    name_he = str(name_he or "").strip()
    for row in records:
        db_name = str(row.get("שם האטרקציה") or "").strip().casefold()
        if name_en and db_name and (name_en == db_name or name_en in db_name or db_name in name_en):
            return row
    if name_he:
        for row in records:
            aliases = [a.strip() for a in re.split(r"[,•;]", str(row.get("כינויים בעברית") or "")) if a.strip()]
            if any(a == name_he or (len(a) > 3 and (a in name_he or name_he in a)) for a in aliases):
                return row
    return None


def _wiki_image(name_en, city):
    """Thumbnail of the Wikipedia article that best matches the place."""
    if not name_en:
        return ""
    try:
        resp = requests.get(_WIKI_API, headers=_WIKI_HEADERS, timeout=6, params={
            "action": "query", "format": "json", "generator": "search",
            "gsrsearch": f"{name_en} {city or ''}".strip(), "gsrlimit": 1,
            "prop": "pageimages", "piprop": "thumbnail", "pithumbsize": 480,
        })
        pages = (resp.json().get("query") or {}).get("pages") or {}
        for page in pages.values():
            thumb = (page.get("thumbnail") or {}).get("source")
            if thumb:
                return thumb
    except Exception:
        logging.info("Wikipedia image lookup failed for %s", name_en)
    return ""


def _parse_json(raw):
    raw = str(raw or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").replace("json", "", 1).strip()
    return json.loads(raw[raw.index("{"):raw.rindex("}") + 1])


def core_itinerary_text(text):
    """The day-by-day part only: drops the intro before the first day and a
    closing question/notes after the last one. Used for the plain-text
    fallback while the cards aren't built yet."""
    lines = str(text or "").splitlines()
    first = next((i for i, ln in enumerate(lines) if _DAY_LINE.search(ln)), None)
    if first is None:
        return str(text or "").strip()
    lines = lines[first:]
    note_start = re.compile(r"^\W*(?:הערה|הערות|טיפ|חשוב|שימו לב|שימי לב|לתשומת לבך|נ\.?ב)")
    while lines and (
        not lines[-1].strip()
        or lines[-1].strip().endswith("?")
        or note_start.match(lines[-1].strip())
    ):
        lines.pop()
    return "\n".join(lines).strip()


def build_itinerary_days(text, answers, post_claude, key, model):
    """Structured day cards for an approved itinerary, or [] on failure."""
    core = core_itinerary_text(text)
    if not core:
        return []
    context = f"תאריך יציאה: {answers.get('departure_date') or 'לא ידוע'}, תאריך חזרה: {answers.get('return_date') or 'לא ידוע'}"
    try:
        raw = post_claude(key, model, _STRUCTURE_PROMPT, context, [], "המסלול שאושר:\n" + core, 6000, include_history=False)
        days = _parse_json(raw).get("days") or []
    except Exception:
        logging.exception("Itinerary structuring failed")
        return []
    records = _load_db()
    result = []
    for d in days:
        if not isinstance(d, dict):
            continue
        items = []
        for it in d.get("items") or []:
            if not isinstance(it, dict) or not str(it.get("name_he") or it.get("name_en") or "").strip():
                continue
            name_he = str(it.get("name_he") or "").strip()
            name_en = str(it.get("name_en") or "").strip()
            city = str(it.get("city") or d.get("city") or "").strip()
            match = _db_match(records, name_en, name_he)
            card = {
                "name_he": name_he or name_en,
                "name_en": name_en if name_en and name_en != name_he else "",
                "city": city,
                "description": str(it.get("description") or "").strip(),
                "duration": str(it.get("duration") or (match or {}).get("משך מומלץ") or "").strip(),
                "price": str((match or {}).get("מחיר/הערת מחיר") or "").strip(),
                "tickets_url": str((match or {}).get("קישור הזמנה/כרטיסים") or "").strip(),
                "official_url": str((match or {}).get("אתר רשמי") or "").strip(),
                "kids": str((match or {}).get("מתאים לילדים") or "").strip(),
                "map_url": "https://www.google.com/maps/search/?api=1&query=" + quote_plus(f"{name_en or name_he} {city}".strip()),
                "image": _wiki_image(name_en, city),
            }
            if card["official_url"] == card["tickets_url"]:
                card["official_url"] = ""
            items.append(card)
        result.append({
            "day": d.get("day"),
            "date": str(d.get("date") or "").strip(),
            "title": str(d.get("title") or "").strip(),
            "city": str(d.get("city") or "").strip(),
            "base": str(d.get("base") or "").strip(),
            "summary": str(d.get("summary") or "").strip(),
            "items": items,
        })
    return result
