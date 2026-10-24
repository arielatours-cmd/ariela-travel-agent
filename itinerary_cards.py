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
import html
import json
import logging
import os
import re
from urllib.parse import quote_plus

from datetime import date, datetime

import requests

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
# Explicit curated files plus anything attractions_coverage.py adds
# automatically for a newly-researched country (attractions_auto_*.json) -
# discovered dynamically so a new country becomes usable the moment the
# background research job writes its file, no code change/deploy needed.
_DB_FILES = ("attractions.json", "attractions_global30.json", "attractions_global30_extra.json", "attractions_malta.json")
_WIKI_API = "https://en.wikipedia.org/w/api.php"
_WIKI_HEADERS = {"User-Agent": "AriellaTravelAgent/1.0 (itinerary cards)"}

_DAY_LINE = re.compile(
    r"(?<![א-ת])יום\s+(?:\d{1,2}(?!\d)|(?:ה?(?:ראשון|שני|שלישי|רביעי|חמישי|שישי|שבת|אחרון)))"
)

# A non-Hebrew itinerary's day lines, by structure: the line opens with
# "Day <number>" (the numbered-day format the plan is written in).
_DAY_LINE_START = re.compile(r"^\W*Day\s+\d{1,2}(?!\d)", re.IGNORECASE)

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

# The same structuring step for a vacation whose customer chats in another
# language (answers["_lang"], a general language code - "en" today, more later;
# Shlomo/business owner 24.10): the itinerary is created in the customer's
# language, not translated - an instruction to the model, same schema and keys,
# one call. "name" is the place's display name. {language} is filled in by
# _structure_prompt_for; any code other than "he" uses this one template.
_STRUCTURE_PROMPT_FOREIGN = """You convert an approved trip itinerary (free text) into JSON for itinerary cards.
Rules:
- Include only days and places that appear in the text. Do not add attractions that were not mentioned.
- Use only the day-by-day plan: ignore any introduction, closing question or side notes around it.
- items are specific places to visit (a site, museum, park, neighborhood, beach, a named recommended restaurant) - not general activities such as "dinner", "rest" or "drive".
- description: 1-2 sentences in {language} - what the place is and why it is worth visiting, in a friendly tone. No prices, no opening hours and no links.
- name: the place's name as the itinerary gives it, in {language}.
- name_en: the place's commonly used English name (as on Wikipedia/maps), or null if it has no specific name.
- duration: a short recommended visit length, in {language}, or null.
- date: YYYY-MM-DD if it can be inferred from the text or the given departure date, otherwise null.
- base: the town/area where the night is spent, if stated, otherwise null.
- Write every text field (title, city, base, summary, name, description, duration) in {language}.
Return JSON only, in this format:
{{"days":[{{"day":1,"date":null,"title":"","city":"","base":null,"summary":"","items":[{{"name":"","name_en":null,"city":"","description":"","duration":null}}]}}]}}"""
# Language names for the model; an unknown code is passed as is (the model
# understands ISO codes too). Adding a language needs no code change.
_LANGUAGE_NAMES = {"en": "English", "fr": "French", "de": "German", "es": "Spanish", "it": "Italian",
                   "ru": "Russian", "ar": "Arabic", "pt": "Portuguese", "nl": "Dutch"}


_LANG_CODE = re.compile(r"^[a-z]{2,3}$")


def _vacation_lang(answers):
    """The vacation's language code; missing, empty or anything that isn't a
    plain 2-3 letter code means Hebrew - free text never reaches the prompt."""
    code = str((answers or {}).get("_lang") or "").strip().lower()
    return code if _LANG_CODE.match(code) else "he"


def _structure_prompt_for(lang):
    return _STRUCTURE_PROMPT_FOREIGN.format(language=_LANGUAGE_NAMES.get(lang, lang))


def _load_db():
    try:
        auto_files = [f for f in os.listdir(_DATA_DIR) if f.startswith("attractions_auto_") and f.endswith(".json")]
    except FileNotFoundError:
        auto_files = []
    records = []
    for filename in (*_DB_FILES, *auto_files):
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


# Din (IMG-1, 23.10): Wikimedia photos only under PD / CC0 / CC BY / CC BY-SA,
# each shown with a credit linking to its Commons page; anything else -> no photo.
_ALLOWED_IMAGE_LICENSES = re.compile(r"^(public domain|pd\b|cc0|cc by(-sa)?( \d(\.\d)?)?)", re.IGNORECASE)


# Din (IMG-1): a known author only. Any value made only of "unknown"/"anonymous"
# words plus a role word ("Unknown artist", "Anonymous (photographer)", "author
# unknown", "N/A") is no author - whatever the punctuation or parentheses.
_UNKNOWN_WORDS = {"unknown", "anonymous", "anon", "unidentified", "unnamed"}
_UNKNOWN_PHRASES = (["n", "a"], ["na"], ["not", "known"])
_ROLE_WORDS = {"artist", "author", "photographer", "photo", "creator", "painter", "by"}


def _is_unknown_artist(text):
    words = re.findall(r"[^\W\d_]+", str(text or "").lower())
    core = [w for w in words if w not in _ROLE_WORDS]
    return not core or core in _UNKNOWN_PHRASES or set(core) <= _UNKNOWN_WORDS


def _commons_text(raw):
    """Plain text from a Commons extmetadata HTML value. Hidden elements
    (display:none - e.g. "Anonymous" followed by a hidden "Unknown author",
    Tom's QA on File:Ponte Vecchio, Florence.jpg) are dropped before the
    tags, then entities are decoded."""
    text = str(raw or "")
    text = re.sub(r"<(\w+)[^>]*display\s*:\s*none[^>]*>.*?</\1>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    for _ in range(3):  # double-escaped entities too ("&amp;amp;")
        unescaped = html.unescape(text)
        if unescaped == text:
            break
        text = unescaped
    return re.sub(r"\s+", " ", text).strip()


def _image_license(file_title):
    """Licence metadata for a Wikipedia page image: {"artist", "license",
    "page"} when the file is on Commons under an allowed licence, else None
    (a local "fair use" file, NC/ND, unknown author or licence)."""
    if not file_title:
        return None
    try:
        resp = requests.get(_WIKI_API, headers=_WIKI_HEADERS, timeout=6, params={
            "action": "query", "format": "json", "titles": f"File:{file_title}",
            "prop": "imageinfo", "iiprop": "extmetadata|url",
            "iiextmetadatafilter": "LicenseShortName|Artist",
        })
        for page in ((resp.json().get("query") or {}).get("pages") or {}).values():
            info = (page.get("imageinfo") or [{}])[0]
            meta = info.get("extmetadata") or {}
            license_name = _commons_text((meta.get("LicenseShortName") or {}).get("value"))
            artist = _commons_text((meta.get("Artist") or {}).get("value"))
            if _is_unknown_artist(artist):
                artist = ""  # Din: a known author only
            page_url = str(info.get("descriptionurl") or "")
            if (page_url.startswith("https://commons.wikimedia.org/") and artist and license_name
                    and _ALLOWED_IMAGE_LICENSES.match(license_name) and not re.search(r"\b(nc|nd)\b", license_name.lower())):
                return {"artist": artist, "license": license_name, "page": page_url}
    except Exception:
        logging.info("Wikimedia licence lookup failed for %s", file_title)
    return None


def _wiki_image_licensed(name_en, city):
    """(thumbnail, credit) for the place's Wikipedia page image - only when
    the file's licence allows it (see _image_license); else ("", None)."""
    if not name_en:
        return "", None
    try:
        resp = requests.get(_WIKI_API, headers=_WIKI_HEADERS, timeout=6, params={
            "action": "query", "format": "json", "generator": "search",
            "gsrsearch": f"{name_en} {city or ''}".strip(), "gsrlimit": 1,
            "prop": "pageimages", "piprop": "thumbnail|name", "pithumbsize": 480,
        })
        for page in ((resp.json().get("query") or {}).get("pages") or {}).values():
            thumb = (page.get("thumbnail") or {}).get("source")
            credit = _image_license(page.get("pageimage")) if thumb else None
            if thumb and credit:
                return thumb, credit
    except Exception:
        logging.info("Wikipedia image lookup failed for %s", name_en)
    return "", None


def _parse_json(raw):
    raw = str(raw or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").replace("json", "", 1).strip()
    return json.loads(raw[raw.index("{"):raw.rindex("}") + 1])


def core_itinerary_text(text, lang=None):
    """The day-by-day part only: drops the intro before the first day and a
    closing question/notes after the last one. Used for the plain-text
    fallback while the cards aren't built yet.

    Hebrew (lang missing/"he" - every vacation today) is exactly the original
    logic. Another language is trimmed by structure only, never by a word
    list (business owner's rule): it starts at the first line that opens with
    "Day <number>" and drops trailing blank/question lines; with no such line
    the text is kept whole."""
    if _vacation_lang({"_lang": lang}) != "he":
        return _core_itinerary_text_by_structure(text)
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


def _core_itinerary_text_by_structure(text):
    lines = str(text or "").splitlines()
    first = next((i for i, ln in enumerate(lines) if _DAY_LINE_START.match(ln)), None)
    if first is None:
        return str(text or "").strip()
    lines = lines[first:]
    while lines and (not lines[-1].strip() or lines[-1].strip().endswith("?")):
        lines.pop()
    return "\n".join(lines).strip()


# Structured price fields per attraction (product/attraction-prices.md) -
# copied onto each card; what is actually shown is decided at render time by
# attraction_price_view (the 90-day validity depends on the day it's shown).
_PRICE_FIELDS = ("price_adult", "price_child", "child_age_range", "free_under_age", "currency",
                 "free_entry", "price_status", "price_checked_at")
PRICE_MAX_AGE_DAYS = 90
# Din's approved wording (DEAL-18, simplified version of 22.10) - never
# reworded; only the amount/unit are filled in. No check date beside it.
PRICE_TEXT = "מחיר משוער: כ-{amount} לאדם. המחיר הסופי באתר ההזמנה."
# Din (PR #148 review): when not everyone pays the adult price.
PRICE_TEXT_PER_ADULT = (
    "מחיר משוער: כ-{amount} למבוגר. לפי מחיר מבוגר × {n}: כ-{total} (לילדים ייתכן מחיר נמוך יותר). "
    "המחיר הסופי באתר ההזמנה."
)
FREE_ENTRY_TEXT = "כניסה חינם"
_CURRENCY_SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£", "ILS": "₪"}


def _money(amount, currency):
    value = f"{amount:,.0f}" if float(amount) == int(amount) else f"{amount:,.2f}"
    symbol = _CURRENCY_SYMBOLS.get(currency)
    return f"{symbol}{value}" if symbol else f"{value} {currency}"


def _age_range(text):
    """(low, high) inclusive from the DB's child_age_range ("4-12", "עד 17
    ..."), or None when it doesn't state a plain range."""
    raw = str(text or "")
    m = re.match(r"\s*(\d{1,2})\s*[-–]\s*(\d{1,2})(?!\d)", raw)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.match(r"\s*עד\s*(\d{1,2})(?!\d)", raw)
    if m:
        return 0, int(m.group(1))
    return None


def _same_price_for_everyone(info, answers):
    """True only when every traveler in the party certainly pays the adult
    price: adults only, or every child's age known and outside both the
    free age and the child price range. Anything else (a discount or free
    entry for someone, an unknown age, an unreadable child rule) -> False."""
    try:
        children = max(0, int(answers.get("children") or 0))
    except (TypeError, ValueError):
        return False
    if not children:
        return True
    ages = answers.get("age_groups") if isinstance(answers.get("age_groups"), list) else []
    if len(ages) < children:
        return False
    free_under = info.get("free_under_age")
    child_range = _age_range(info.get("child_age_range"))
    if info.get("child_age_range") and not child_range:
        return False
    child_price = info.get("price_child")
    if child_price is not None and child_price != info.get("price_adult") and not child_range:
        # Shaked (PR #148 review): a different child price with no readable
        # age range - we can't tell which children it applies to.
        return False
    for age in ages[:children]:
        try:
            age = int(age)
        except (TypeError, ValueError):
            return False
        if isinstance(free_under, int) and not isinstance(free_under, bool) and age <= free_under:
            return False
        if child_range and child_range[0] <= age <= child_range[1] and info.get("price_child") != info.get("price_adult"):
            return False
    return True


def _certainly_free_children(info, answers):
    """How many children in the party certainly enter free: known age at or
    under free_under_age (inclusive, as the DB stores it)."""
    free_under = info.get("free_under_age")
    if not isinstance(free_under, int) or isinstance(free_under, bool):
        return 0
    try:
        children = max(0, int(answers.get("children") or 0))
    except (TypeError, ValueError):
        return 0
    ages = answers.get("age_groups") if isinstance(answers.get("age_groups"), list) else []
    free = 0
    for age in ages[:children]:
        try:
            free += int(age) <= free_under
        except (TypeError, ValueError):
            continue
    return free


def attraction_price_view(info, answers, today=None):
    """The one price line that may be shown next to an attraction card, per
    Din's conditions (DEAL-18, simplified wording, relayed 22.10), or None
    to show no price at all (the links stay either way):

    1. only a verified price (price_status == "ok");
    2. only when checked within PRICE_MAX_AGE_DAYS (the date isn't shown,
       but an unknown or older date still means no price);
    3. "לאדם" only when everyone in the party pays the same adult price;
       otherwise (a different price by age/party, or unknown ages) the
       adult price and "לפי מחיר מבוגר × N: כ-<total>" (PRICE_TEXT_PER_ADULT);
    4. in the source currency, no conversion;
    5. "כניסה חינם" only when free_entry is verified (same 1+2);
    6. Din's wording, exactly (PRICE_TEXT / PRICE_TEXT_PER_ADULT).
    free_under_age is inclusive (the DB stores 17 for "free under 18")."""
    info = info if isinstance(info, dict) else {}
    answers = answers if isinstance(answers, dict) else {}
    if info.get("price_status") != "ok":
        return None
    try:
        checked = datetime.strptime(str(info.get("price_checked_at") or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    today = today or date.today()
    if (today - checked).days > PRICE_MAX_AGE_DAYS or checked > today:
        return None
    if info.get("free_entry") is True:
        return {"text": FREE_ENTRY_TEXT}
    adult = info.get("price_adult")
    currency = str(info.get("currency") or "").strip().upper()
    if not isinstance(adult, (int, float)) or isinstance(adult, bool) or adult <= 0 or not re.fullmatch(r"[A-Z]{3}", currency):
        return None
    try:
        travelers = max(0, int(answers.get("adults") or 0)) + max(0, int(answers.get("children") or 0))
    except (TypeError, ValueError):
        travelers = 0
    if travelers <= 1 or _same_price_for_everyone(info, answers):
        return {"text": PRICE_TEXT.format(amount=_money(adult, currency))}
    # Shlomo (PR #148 review): a child certainly free (known age <= free_
    # under_age) isn't counted in N, so the total isn't inflated.
    paying = max(1, travelers - _certainly_free_children(info, answers))
    return {"text": PRICE_TEXT_PER_ADULT.format(amount=_money(adult, currency), n=paying,
                                                total=_money(adult * paying, currency))}


# Din (PR #148 review): a ticket link is shown only on the official site's
# own domain, or at an official ticketing operator the official site itself
# sends buyers to (this manual list) - never a reseller.
OFFICIAL_TICKET_OPERATORS = {
    "parkovihrvatske.hr",      # Croatia's national parks ticketing (Plitvice, Krka)
    "imperialtickets.com",     # Schönbrunn's own ticket shop
    "cityexperiences.com",     # Statue City Cruises - the NPS concession (Statue of Liberty)
    "tickets.atthetop.ae",     # Burj Khalifa "At the Top"
    "ticketlouvre.fr",         # the Louvre's ticketing site
    "thedubaiaquarium.com",    # Dubai Aquarium's own site
}


def _host(url):
    from urllib.parse import urlsplit
    host = (urlsplit(str(url or "").strip()).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _same_site(a, b):
    return bool(a and b) and (a == b or a.endswith("." + b) or b.endswith("." + a))


def attraction_tickets_url(tickets_url, official_url):
    """The ticket link to show, or "" (Din's rule above). An empty
    official_url here means it equalled the ticket link when the card was
    built (build_itinerary_days drops the duplicate) - same site."""
    tickets = str(tickets_url or "").strip()
    if not tickets:
        return ""
    official = str(official_url or "").strip()
    host = _host(tickets)
    if not official or _same_site(host, _host(official)):
        return tickets
    return tickets if any(_same_site(host, op) for op in OFFICIAL_TICKET_OPERATORS) else ""


def build_itinerary_days(text, answers, post_claude, key, model):
    """Structured day cards for an approved itinerary, or [] on failure."""
    core = core_itinerary_text(text, (answers or {}).get("_lang"))
    if not core:
        return []
    lang = _vacation_lang(answers)
    foreign = lang != "he"
    if foreign:
        context = f"Departure date: {answers.get('departure_date') or 'unknown'}, return date: {answers.get('return_date') or 'unknown'}"
        prompt, message = _structure_prompt_for(lang), "Approved itinerary:\n" + core
    else:
        context = f"תאריך יציאה: {answers.get('departure_date') or 'לא ידוע'}, תאריך חזרה: {answers.get('return_date') or 'לא ידוע'}"
        prompt, message = _STRUCTURE_PROMPT, "המסלול שאושר:\n" + core
    try:
        raw = post_claude(key, model, prompt, context, [], message, 6000, include_history=False)
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
            if not isinstance(it, dict) or not str(it.get("name_he") or it.get("name") or it.get("name_en") or "").strip():
                continue
            # name_he is the card's display name; a non-Hebrew itinerary's model
            # output calls it "name" (and it is never matched as Hebrew below).
            display = (it.get("name") or it.get("name_he")) if foreign else it.get("name_he")
            name_he = str(display or "").strip()
            name_en = str(it.get("name_en") or "").strip()
            city = str(it.get("city") or d.get("city") or "").strip()
            match = _db_match(records, name_en, "" if foreign else name_he)
            card = {
                "name_he": name_he or name_en,
                "name_en": name_en if name_en and name_en != name_he else "",
                "city": city,
                "description": str(it.get("description") or "").strip(),
                # Catalog duration in the vacation's language: "משך מומלץ" for
                # Hebrew, duration_<lang> otherwise (only duration_en exists
                # today) - never the Hebrew value on a non-Hebrew vacation.
                "duration": str(it.get("duration") or (match or {}).get(f"duration_{lang}" if foreign else "משך מומלץ") or "").strip(),
                # Structured, verified price data only (Din, 22.10) - the old
                # free-text price note is no longer shown.
                "price_info": {f: (match or {}).get(f) for f in _PRICE_FIELDS},
                "tickets_url": str((match or {}).get("קישור הזמנה/כרטיסים") or "").strip(),
                "official_url": str((match or {}).get("אתר רשמי") or "").strip(),
                "kids": str((match or {}).get("מתאים לילדים") or "").strip(),
                "map_url": "https://www.google.com/maps/search/?api=1&query=" + quote_plus(f"{name_en or name_he} {city}".strip()),
            }
            card["image"], card["image_credit"] = _wiki_image_licensed(name_en, city)
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
