"""Din — legal/terms verification layer for Ariella flight deals.

Din checks fare-level/provider text first and, when needed, official airline pages.
The result is deliberately conservative: if an exact rule cannot be established for
this fare, Ariella shows "יש לבדוק באתר הספק" rather than guessing.
"""
from __future__ import annotations

import html
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests

_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_SECONDS = 24 * 60 * 60
_TIMEOUT = 8
_MAX_POLICY_PAGES = 4

# Official carrier pages used as strong starting points. Unknown carriers are still
# checked from a direct-airline booking URL when one is available in the deal.
AIRLINE_POLICY_SOURCES = {
    # Foreign carriers flying to/from Israel are required to publish an
    # explicit "Israel Consumer Protection Law" notice - most of the entries
    # below now point straight at that dedicated page (confirmed to exist and
    # to name the law) instead of a generic homepage/help-center URL, so
    # Din's explicit-mention check actually has a real page to find it on.
    # A carrier left on a generic URL here is one no such dedicated page
    # could be confirmed for - Din correctly keeps showing "check" for it
    # rather than guessing.
    "el al": "https://www.elal.com/eng/useful-info/policies",
    "אל על": "https://www.elal.com/eng/useful-info/policies",
    "arkia": "https://www.arkia.co.il/he/content/cancel-reservation",
    "ארקיע": "https://www.arkia.co.il/he/content/cancel-reservation",
    "israir": "https://www.israir.co.il/Passengers_Info/Cancel_Remote_Sale_Policy",
    "ישראייר": "https://www.israir.co.il/Passengers_Info/Cancel_Remote_Sale_Policy",
    "wizz air": "https://wizzair.com/en-gb/information-and-services/booking-information/changing-your-reservation",
    "ryanair": "https://help.ryanair.com/hc/en-gb/categories/12489112419089-Changes-Refunds",
    "easyjet": "https://www.easyjet.com/en/help/booking-and-check-in/managing-your-booking",
    "aegean": "https://en.aegeanair.com/plan/fare-rules/",
    "aegean airlines": "https://en.aegeanair.com/plan/fare-rules/",
    "lufthansa": "https://www.lufthansa.com/",
    "ita airways": "https://www.ita-airways.com/il/en/local-page/consumer-protection",
    "air france": "https://wwws.airfrance.com/",
    "klm": "https://www.klm.co.il/information/legal/customer-rights",
    "british airways": "https://www.britishairways.com/",
    "turkish airlines": "https://www.turkishairlines.com/",
    "emirates": "https://www.emirates.com/english/information/consumer-law-notice/",
    "flydubai": "https://www.flydubai.com/",
    "etihad": "https://www.etihad.com/en-us/legal/israel-consumer-protection-law",
    "etihad airways": "https://www.etihad.com/en-us/legal/israel-consumer-protection-law",
    "lot": "https://www.lot.com/il/en/regulations/consumer-protection-law-cancellation-notice",
    "lot polish airlines": "https://www.lot.com/il/en/regulations/consumer-protection-law-cancellation-notice",
    "bluebird airways": "https://www.bluebirdair.com/",
    "sky express": "https://www.skyexpress.gr/",
    "air haifa": "https://www.airhaifa.com/",
}

_LINK_HINTS = (
    "change", "changes", "cancel", "cancellation", "refund", "fare", "ticket",
    "terms", "conditions", "policy", "policies", "booking", "consumer",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(raw: str) -> str:
    raw = re.sub(r"(?is)<script[^>]*>.*?</script>|<style[^>]*>.*?</style>", " ", raw or "")
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    return re.sub(r"\s+", " ", raw).strip()


def _officialish_url(offer: dict) -> str | None:
    flight = offer.get("flight") or {}
    airline = str(flight.get("airline") or offer.get("airline") or "").strip().casefold()
    if airline in AIRLINE_POLICY_SOURCES:
        return AIRLINE_POLICY_SOURCES[airline]
    for value in (
        flight.get("booking_request_url"), offer.get("booking_url"),
        flight.get("direct_supplier_url"), flight.get("booking_url"),
    ):
        value = str(value or "").strip()
        if not value.startswith(("http://", "https://")):
            continue
        host = (urlparse(value).hostname or "").lower()
        if not host or any(x in host for x in ("google.", "kiwi.", "skyscanner.", "trip.com", "booking.com", "expedia.")):
            continue
        return value
    return None


def _fetch_policy_text(start_url: str) -> tuple[str, list[str]]:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; Ariella-Din/1.0; +https://ariela-travel-agent.onrender.com)"}
    queue = [start_url]
    seen: set[str] = set()
    texts: list[str] = []
    used: list[str] = []
    origin = (urlparse(start_url).scheme, urlparse(start_url).netloc)
    while queue and len(used) < _MAX_POLICY_PAGES:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            response = requests.get(url, headers=headers, timeout=_TIMEOUT, allow_redirects=True)
            if response.status_code >= 400 or "text/html" not in response.headers.get("content-type", "text/html").lower():
                continue
            page = response.text[:1_500_000]
        except requests.RequestException:
            continue
        used.append(response.url)
        texts.append(_clean_text(page)[:250_000])
        if len(used) >= _MAX_POLICY_PAGES:
            break
        for href, label in re.findall(r'(?is)<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', page):
            label_text = _clean_text(label).lower()
            target = urljoin(response.url, html.unescape(href))
            p = urlparse(target)
            if (p.scheme, p.netloc) != origin:
                continue
            token = (target + " " + label_text).lower()
            if any(h in token for h in _LINK_HINTS) and target not in seen and target not in queue:
                queue.append(target)
                if len(queue) > 12:
                    break
    return " ".join(texts), used


def _displayed_price(offer: dict):
    flight = offer.get("flight") or {}
    for value in (flight.get("price"), offer.get("price_ils"), offer.get("price")):
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _fare_text(offer: dict) -> tuple[str, bool]:
    """Return (text, exact) for the fare actually priced on the card.

    Only the fare family whose price matches the displayed price is used - joining
    Basic + Flex features would let Flex's "free change" leak onto the Basic price.
    `exact` is True only when such a matching fare family was found.
    """
    flight = offer.get("flight") or {}
    chunks: list[str] = []
    for key in ("fare_rules", "fare_rule", "ticket_terms", "extensions", "change_cancel"):
        value = flight.get(key) or offer.get(key)
        if isinstance(value, str):
            chunks.append(value)
        elif isinstance(value, (list, tuple)):
            chunks.extend(str(x) for x in value if x)
        elif isinstance(value, dict):
            chunks.extend(str(x) for x in value.values() if x is not None)
    price = _displayed_price(offer)
    exact = False
    for fare in flight.get("fare_options") or offer.get("fare_options") or []:
        if not isinstance(fare, dict):
            continue
        fare_price = fare.get("price_ils")
        if price is None or not isinstance(fare_price, (int, float)) or abs(float(fare_price) - price) > 1:
            continue
        exact = True
        chunks.append(str(fare.get("name") or ""))
        chunks.extend(str(x) for x in (fare.get("features") or []) if x)
    return " ".join(chunks), exact


_CHECK = {"label": "יש לבדוק באתר הספק", "status": "check", "confidence": "low"}

# Wording that negates or limits a positive rule ("no full refund", "free
# cancellation within 24 hours"). Any of these makes the rule uncertain for this
# fare, so Din falls back to "check" instead of picking a side.
_UNCERTAIN_CHANGE_RE = re.compile(
    r"\b(?:no|not|without) (?:a )?(?:full refund|free (?:changes?|cancellation)|change fees?|cancellation fees?)\b"
    r"|\bnot free\b"
    r"|\bwithin \d+ ?(?:hours?|hrs?|days?)\b|\b\d+[- ]?(?:hour|hr|day)s?\b"
    r"|\b(?:only if|only when|up to \d+)\b"
)


def _classify_change_cancel(text: str, exact_fare: bool) -> dict:
    low = text.casefold()
    if _UNCERTAIN_CHANGE_RE.search(low):
        return dict(_CHECK)
    # Exact fare/provider statements take precedence over generic airline help text.
    if re.search(r"\b(non[- ]?refundable|no refunds?|not refundable|non[- ]?changeable|changes? not (?:allowed|permitted))\b", low):
        return {"label": "לא ניתן לשינוי או ביטול", "status": "none", "confidence": "high" if exact_fare else "medium"}
    if re.search(r"\b(free changes?|change without (?:a )?fee|free cancellation|full refund)\b", low):
        return {"label": "אפשרי ללא תשלום", "status": "free", "confidence": "high" if exact_fare else "medium"}
    if re.search(r"\b(change fee|changes? (?:are )?(?:allowed|permitted)|cancellation fee|refund fee|refundable with|subject to (?:a )?fee)\b", low):
        return {"label": "אפשרי בתשלום", "status": "paid", "confidence": "high" if exact_fare else "medium"}
    return dict(_CHECK)


_LAW_MENTION_RE = re.compile(
    r"חוק הגנת הצרכן|israeli? consumer protection law|consumer protection law,? 1981"
)
# A mention inside a negating or conditional sentence ("does not apply",
# "applies only to tickets purchased in Israel") is not a statement that the law
# applies to this purchase.
_LAW_LIMIT_RE = re.compile(
    r"אינו חל|אינה חלה|לא חל|לא יחול|בלבד|רק אם|רק כאשר|למעט|אלא אם"
    r"|does not apply|do not apply|shall not apply|not applicable|n't apply"
    r"|only (?:if|when|to|for|applies)|except|unless|excluding"
)
_LAW_CONTEXT_CHARS = 200


def _classify_consumer_protection(text: str) -> dict:
    low = text.casefold()
    # Never infer that Israeli consumer law applies merely because an airline has
    # a generic refund page. Only an explicit, unqualified reference counts: every
    # mention must be free of negating/conditional wording within ±200 chars.
    mentions = list(_LAW_MENTION_RE.finditer(low))
    if mentions and all(
        not _LAW_LIMIT_RE.search(low[max(0, m.start() - _LAW_CONTEXT_CHARS):m.end() + _LAW_CONTEXT_CHARS])
        for m in mentions
    ):
        return {"status": "applies", "label": "חלה", "confidence": "high"}
    return dict(_CHECK)


def _is_generic_homepage(url: str) -> bool:
    """A bare homepage is not a dedicated consumer-law page; crawling it can find
    an unrelated mention. Din keeps "check" for carriers mapped to one."""
    p = urlparse(url)
    return p.path.strip("/") == "" and not p.query


def _cached_airline_check(airline_key: str, start_url: str) -> dict:
    cache_key = airline_key or start_url
    now = time.time()
    cached = _CACHE.get(cache_key)
    if cached and now - cached[0] < _CACHE_SECONDS:
        return cached[1]
    text, urls = _fetch_policy_text(start_url)
    result = {"text": text, "source_urls": urls, "checked_at": _now_iso()}
    _CACHE[cache_key] = (now, result)
    return result


def enrich_offer_legal_terms(offer: dict) -> dict:
    """Return the offer enriched with Din's conservative legal/terms findings."""
    if not isinstance(offer, dict):
        return offer
    flight = offer.get("flight") or {}
    airline = str(flight.get("airline") or offer.get("airline") or "").strip()
    fare_text, exact_fare = _fare_text(offer)
    # The fare families come from direct-airline booking options only. When the
    # card sends the customer to an agency, neither the fare rules nor the
    # airline's consumer-law notice describe that purchase - keep "check".
    # Unknown (None) is treated like an agency.
    direct = flight.get("booking_supplier_is_direct") is True

    change = _classify_change_cancel(fare_text, exact_fare=exact_fare) if (direct and fare_text.strip()) else dict(_CHECK)
    protection = dict(_CHECK)
    sources: list[str] = []
    checked_at = _now_iso()

    start_url = _officialish_url(offer)
    if start_url and direct and not _is_generic_homepage(start_url):
        policy = _cached_airline_check(airline.casefold(), start_url)
        checked_at = policy.get("checked_at") or checked_at
        sources = policy.get("source_urls") or []
        official_text = policy.get("text") or ""
        if change.get("status") == "check" and official_text:
            generic_change = _classify_change_cancel(official_text, exact_fare=False)
            # General airline policies can show that changes/refunds exist, but not
            # that this specific fare qualifies. Keep the customer-facing fallback
            # unless wording is exact enough in provider/fare data.
            if generic_change.get("status") != "check":
                change["general_policy"] = generic_change
        if official_text:
            protection = _classify_consumer_protection(official_text)

    change.update({"checked_by": "Din", "checked_at": checked_at, "source_urls": sources})
    protection.update({"checked_by": "Din", "checked_at": checked_at, "source_urls": sources})
    offer["change_cancel"] = change
    offer["consumer_protection"] = protection
    offer["din_verification"] = {
        "checked_at": checked_at,
        "airline": airline or None,
        "source_urls": sources,
        "change_cancel_status": change.get("status"),
        "consumer_protection_status": protection.get("status"),
    }
    return offer
