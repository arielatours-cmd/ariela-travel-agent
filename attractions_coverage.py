"""Keeps data/attractions*.json in step with every destination country a
customer actually talks about, instead of relying on someone noticing a
gap live (as happened with Malta) and filling it by hand.

Per product owner: the moment a new country enters a conversation, check
whether the attractions DB already covers it. If not, research it for
real via SerpAPI web search (the same provider already paid for and used
for flights/hotels) and add entries built only from what the search
actually returned - never from the model's own unverified recall. This
mirrors exactly the manual process used to add Malta's 10 entries.

Runs as a fire-and-forget background thread so it never slows down the
customer's chat turn, and is safe to call repeatedly - already-covered or
already-in-progress countries are cheap no-ops.
"""
import json
import logging
import os
import re
import threading
from datetime import date

from scanner import _serpapi_request, _api_key as _serpapi_key

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
_AUTO_FILE_PREFIX = "attractions_auto_"

_COVERAGE_LOCK = threading.Lock()
_IN_PROGRESS: set[str] = set()

_RESEARCH_PROMPT = """את בונה רשומות אטרקציות למאגר נתונים של סוכנות נסיעות, אך ורק מתוך תוצאות חיפוש אמיתיות שסופקו לך למטה - אסור להשתמש בידע כללי משלך על אטרקציות, מחירים או קישורים שלא מופיעים בתוצאות.

כללים:
- בני עד 8 רשומות, רק עבור אטרקציות/אתרים שהוזכרו בפועל בתוצאות החיפוש שסופקו.
- "מחיר/הערת מחיר": רק אם מחיר כלשהו מופיע במפורש באחת מהתוצאות (מספר/טווח/מטבע) - אחרת תני null. אל תנחשי ואל תעגלי.
- "אתר רשמי" ו"קישור הזמנה/כרטיסים": רק קישורים (URL) שמופיעים בפועל בתוצאות החיפוש שסופקו (בשדה link). אם אין קישור רלוונטי ברור לאטרקציה הספציפית - תני מחרוזת ריקה.
- "שם האטרקציה": השם המקובל באנגלית, כפי שמופיע בתוצאות.
- "כינויים בעברית": תרגום/כינוי עברי טבעי לאטרקציה (לא תעתיק פונטי מומצא), 1-3 חלופות מופרדות בפסיק.
- "מחיר/הערת מחיר" יכול גם להיות "ללא עלות כניסה" אם תוצאה מציינת במפורש שהכניסה חינם.
- "משך מומלץ": הערכה סבירה קצרה (שעה, חצי יום וכו') רק אם יש רמז ברור בתוצאות, אחרת null.
- "מתאים לילדים": "כן"/"לא"/"חלקית" רק אם יש רמז בתוצאות, אחרת null.

החזירי JSON בלבד בפורמט:
{"attractions":[{"שם האטרקציה":"","כינויים בעברית":"","סוג ראשי":"","מתאים לילדים":null,"משך מומלץ":null,"מחיר/הערת מחיר":null,"אתר רשמי":"","קישור הזמנה/כרטיסים":"","הערות":""}]}"""


def _attraction_files():
    try:
        return [f for f in os.listdir(_DATA_DIR) if f.startswith("attractions") and f.endswith(".json")]
    except FileNotFoundError:
        return []


def _covered_countries() -> set[str]:
    """Every distinct 'מדינה' value already present in any attractions file."""
    covered = set()
    for filename in _attraction_files():
        try:
            with open(os.path.join(_DATA_DIR, filename), "r", encoding="utf-8") as fh:
                payload = json.load(fh)
            rows = payload.get("attractions", []) if isinstance(payload, dict) else payload
            for row in rows:
                if isinstance(row, dict) and row.get("מדינה"):
                    covered.add(str(row["מדינה"]).strip())
        except Exception:
            logging.exception("Could not read attraction file %s for coverage check", filename)
    return covered


def _safe_filename_token(country_en: str) -> str:
    token = re.sub(r"[^a-zA-Z0-9]+", "_", str(country_en or "").strip()).strip("_").lower()
    return token or "country"


def _search_country_attractions(country_en: str) -> list[dict]:
    """Real web search results about the country's top attractions -
    organic results only (title/link/snippet), nothing synthesized."""
    params = {
        "engine": "google",
        "q": f"top tourist attractions {country_en} official site tickets price",
        "num": 10,
        "hl": "en",
        "api_key": _serpapi_key(),
    }
    data = _serpapi_request(params)
    results = data.get("organic_results") or []
    out = []
    for r in results:
        if not isinstance(r, dict):
            continue
        title = str(r.get("title") or "").strip()
        link = str(r.get("link") or "").strip()
        snippet = str(r.get("snippet") or "").strip()
        if title and link:
            out.append({"title": title, "link": link, "snippet": snippet})
    return out


def _parse_json(raw):
    raw = str(raw or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").replace("json", "", 1).strip()
    return json.loads(raw[raw.index("{"):raw.rindex("}") + 1])


def _research_and_write(country_he: str, country_en: str, post_claude, key: str, model: str) -> int:
    """Returns the number of attraction rows written, 0 on failure/no data."""
    try:
        search_results = _search_country_attractions(country_en)
    except Exception:
        logging.exception("Attraction search failed for %s", country_en)
        return 0
    if not search_results:
        return 0
    context = "תוצאות חיפוש אמיתיות (JSON):\n" + json.dumps(search_results, ensure_ascii=False)
    try:
        raw = post_claude(key, model, _RESEARCH_PROMPT, "", [], context, 3000, include_history=False, source="internal_attractions")
        rows = _parse_json(raw).get("attractions") or []
    except Exception:
        logging.exception("Attraction extraction failed for %s", country_en)
        return 0
    today = date.today().isoformat()
    records = []
    for row in rows:
        if not isinstance(row, dict) or not str(row.get("שם האטרקציה") or "").strip():
            continue
        record = {
            "מדינה": country_he,
            "אזור/מחוז": "",
            "עיר/בסיס": "",
            "שם האטרקציה": str(row.get("שם האטרקציה") or "").strip(),
            "כינויים בעברית": str(row.get("כינויים בעברית") or "").strip(),
            "סוג ראשי": str(row.get("סוג ראשי") or "").strip(),
            "מתאים לילדים": str(row.get("מתאים לילדים") or "").strip(),
            "משך מומלץ": str(row.get("משך מומלץ") or "").strip(),
            "מחיר/הערת מחיר": str(row.get("מחיר/הערת מחיר") or "").strip(),
            "אתר רשמי": str(row.get("אתר רשמי") or "").strip(),
            "קישור הזמנה/כרטיסים": str(row.get("קישור הזמנה/כרטיסים") or "").strip(),
            "הערות": str(row.get("הערות") or "").strip(),
            "מקור": "חיפוש אוטומטי",
            "נבדק לאחרונה": today,
        }
        records.append(record)
    if not records:
        return 0
    filename = f"{_AUTO_FILE_PREFIX}{_safe_filename_token(country_en)}.json"
    path = os.path.join(_DATA_DIR, filename)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"attractions": records}, fh, ensure_ascii=False, indent=2)
    logging.info("Added %d attraction rows for %s (%s) -> %s", len(records), country_he, country_en, filename)
    return len(records)


def ensure_country_coverage(country_he: str, country_en: str | None = None) -> None:
    """Fire-and-forget: if country_he isn't already in the attractions DB,
    research and add it in a background thread. Safe to call on every chat
    turn - already-covered or already-in-progress countries are no-ops."""
    country_he = str(country_he or "").strip()
    if not country_he:
        return
    with _COVERAGE_LOCK:
        if country_he in _IN_PROGRESS:
            return
        if country_he in _covered_countries():
            return
        _IN_PROGRESS.add(country_he)

    def worker():
        try:
            from ariella_chat_clean import _post_claude
            key = os.getenv("ANTHROPIC_API_KEY", "").strip()
            if not key:
                return
            model = os.getenv("ARIELLA_MODEL", "claude-sonnet-5").strip()
            _research_and_write(country_he, country_en or country_he, _post_claude, key, model)
        except Exception:
            logging.exception("Attraction coverage research failed for %s", country_he)
        finally:
            with _COVERAGE_LOCK:
                _IN_PROGRESS.discard(country_he)

    threading.Thread(target=worker, daemon=True, name=f"attractions-coverage-{_safe_filename_token(country_en or country_he)}").start()
