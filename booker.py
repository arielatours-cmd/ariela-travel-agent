"""BOOKER — supplier-aware booking orchestration for Ariella.

BOOKER resolves the safest actionable handoff for the exact round-trip deal.
It does not purchase or submit payment for the customer.
"""

from __future__ import annotations
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit
import os
import requests

from config import SERPAPI_API_KEY


@dataclass
class BookerTarget:
    url: str | None
    fields: list[tuple[str, str]]
    supplier: str
    mode: str
    exact: bool
    note: str = ""


UNRELIABLE_DIRECT_SUPPLIERS = {
    "el al", "elal", "אל על",
}

ACTIONABLE_BOOKING_SUPPLIERS = {
    "trip.com", "expedia", "lastminute.com", "booking.com",
}

BLUEBIRD_NAMES = {
    "bluebird airways", "blue bird airways", "bluebird",
}

OFFICIAL_AIRLINE_BOOKING_FALLBACKS = {
    "bluebird airways": "https://booking.bluebirdair.com/he",
    "blue bird airways": "https://booking.bluebirdair.com/he",
    "bluebird": "https://booking.bluebirdair.com/he",
    "sky express": "https://www.skyexpress.com/",
    "skyexpress": "https://www.skyexpress.com/",
    "air haifa": "https://www.airhaifa.com/",
    "airhaifa": "https://www.airhaifa.com/",
    "אייר חיפה": "https://www.airhaifa.com/",
    "aegean": "https://en.aegeanair.com/",
    "aegean airlines": "https://en.aegeanair.com/",
    "wizz air": "https://wizzair.com/",
    "ryanair": "https://www.ryanair.com/",
    "easyjet": "https://www.easyjet.com/",
    "arkia": "https://www.arkia.com/",
    "ארקיע": "https://www.arkia.com/",
    "israir": "https://www.israir.co.il/",
    "israir airlines": "https://www.israir.co.il/",
    "ישראייר": "https://www.israir.co.il/",
    "el al": "https://www.elal.com/",
    "elal": "https://www.elal.com/",
    "אל על": "https://www.elal.com/",
    "lufthansa": "https://www.lufthansa.com/",
    "air france": "https://www.airfrance.com/",
    "klm": "https://www.klm.com/",
    "ita airways": "https://www.ita-airways.com/",
}


def _norm(value) -> str:
    return str(value or "").strip().lower()


def _homepage(value: str | None) -> str | None:
    """Return a real supplier homepage; never send a booking fallback to Google/SerpApi."""
    try:
        parsed = urlsplit(str(value or ""))
        host = (parsed.netloc or "").lower().split(":", 1)[0]
        blocked = (
            host == "google.com" or host.endswith(".google.com") or
            host == "google.co.il" or host.endswith(".google.co.il") or
            host == "gstatic.com" or host.endswith(".gstatic.com") or
            host == "serpapi.com" or host.endswith(".serpapi.com")
        )
        if parsed.scheme in {"http", "https"} and host and not blocked:
            return f"{parsed.scheme}://{parsed.netloc}/"
    except Exception:
        pass
    return None


def _request_fields(req: dict) -> list[tuple[str, str]]:
    post = req.get("post_data")
    return parse_qsl(post, keep_blank_values=True) if post else []


def _is_unreliable_direct(part: dict) -> bool:
    if part.get("airline") is not True:
        return False
    return _norm(part.get("book_with")) in UNRELIABLE_DIRECT_SUPPLIERS


def _priority(part: dict, preferred_supplier: str) -> tuple[int, float]:
    supplier = _norm(part.get("book_with"))
    same = bool(preferred_supplier and supplier == preferred_supplier)
    direct = bool(part.get("airline") is True)
    actionable = supplier in ACTIONABLE_BOOKING_SUPPLIERS
    try:
        price = float(part.get("price") or 10**9)
    except (TypeError, ValueError):
        price = 10**9
    if _is_unreliable_direct(part):
        return (9, price)
    if same and actionable:
        return (0, price)
    if actionable:
        return (1, price)
    if same and direct:
        return (2, price)
    if direct:
        return (3, price)
    return (4, price)


def _aerocrs_date(value) -> str:
    raw = str(value or "")[:10]
    if len(raw) == 10 and raw[4:5] == "-" and raw[7:8] == "-":
        return raw.replace("-", "/")
    return ""


def _bluebird_deeplink(offer: dict, adults: int, children: int) -> str | None:
    """Ask Bluebird's AeroCRS IBE for a prefilled itinerary handoff.

    The supplier controls the final booking page, but this avoids forcing the
    customer to re-enter route, dates and party size when AeroCRS credentials are
    available in the deployment environment.
    """
    names = (
        offer.get("booking_supplier"), offer.get("airline"),
        offer.get("return_airline"), (offer.get("flight") or {}).get("airline"),
    )
    if not any(_norm(name) in BLUEBIRD_NAMES for name in names):
        return None

    auth_id = (os.getenv("BLUEBIRD_AEROCRS_AUTH_ID") or os.getenv("AEROCRS_AUTH_ID") or "").strip()
    auth_password = (os.getenv("BLUEBIRD_AEROCRS_AUTH_PASSWORD") or os.getenv("AEROCRS_AUTH_PASSWORD") or "").strip()
    if not auth_id or not auth_password:
        return None

    departure = str(offer.get("departure_code") or offer.get("departure_airport") or "").strip().upper()
    arrival = str(offer.get("arrival_code") or offer.get("arrival_airport") or "").strip().upper()
    start = _aerocrs_date(offer.get("outbound_date"))
    end = _aerocrs_date(offer.get("return_date"))
    if not all((departure, arrival, start, end)):
        return None

    params = {
        "from": departure,
        "to": arrival,
        "start": start,
        "end": end,
        "adults": str(max(1, int(adults or 1))),
        "child": str(max(0, int(children or 0))),
        "infant": "0",
        "currency": "ILS",
    }
    flight_number = str(offer.get("flight_number") or "").strip()
    if flight_number:
        params["fltnum"] = flight_number

    try:
        response = requests.get(
            "https://api.aerocrs.com/v5/getDeepLink",
            params=params,
            headers={"auth_id": auth_id, "auth_password": auth_password, "accept": "application/json"},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return None

    def rows(value):
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for key in ("data", "result", "results", "flights"):
                nested = value.get(key)
                if isinstance(nested, list):
                    return nested
                if isinstance(nested, dict):
                    nested_rows = rows(nested)
                    if nested_rows:
                        return nested_rows
            return [value]
        return []

    candidates = []
    for row in rows(payload):
        if not isinstance(row, dict):
            continue
        url = row.get("deeplink") or row.get("deepLink") or row.get("url")
        if not url:
            continue
        score = 0
        row_flight = str(row.get("flight_number") or row.get("fltnum") or row.get("flight") or "").strip().casefold()
        if flight_number and row_flight and flight_number.casefold() in row_flight:
            score += 4
        wanted_time = str(offer.get("departure_time") or "")[-5:]
        row_time = str(row.get("departure_time") or row.get("deptime") or row.get("departure") or "")[-5:]
        if wanted_time and row_time == wanted_time:
            score += 2
        candidates.append((score, str(url)))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def resolve_booking_target(offer: dict, *, adults: int | None = None, children: int | None = None,
                           travel_class: str = "1", regenerate_itinerary: bool = True) -> BookerTarget:
    """Resolve a supplier handoff for the exact itinerary and passenger party.

    A Google Flights booking_token belongs to the search that created it. For a
    personal vacation we therefore regenerate the outbound + return selection
    with the customer's current adults/children before requesting Booking Options.
    """
    recommended = str(offer.get("booking_supplier") or offer.get("airline") or "").strip()
    preferred = _norm(recommended)
    stored_url = offer.get("booking_request_url")
    stored_post = offer.get("booking_request_post_data")
    personal = adults is not None or children is not None
    pax_adults = max(1, int(adults or 1))
    pax_children = max(0, int(children or 0))

    if stored_url and not personal:
        return BookerTarget(url=stored_url,
            fields=parse_qsl(stored_post, keep_blank_values=True) if stored_post else [],
            supplier=recommended, mode="recommended_supplier", exact=True)

    def _time5(value):
        value = str(value or "")
        return value[-5:] if len(value) >= 5 else value

    def _items(data):
        return (data.get("best_flights") or []) + (data.get("other_flights") or [])

    def _summary(item):
        flights = item.get("flights") or []
        first = flights[0] if flights else {}
        dep = first.get("departure_airport") or {}
        airline = str(first.get("airline") or "").strip().lower()
        return _time5(dep.get("time")), airline, len(item.get("layovers") or [])

    def _choose(items, wanted_time, wanted_airline, wanted_stops):
        wanted_time = _time5(wanted_time)
        wanted_airline = str(wanted_airline or "").strip().lower()
        ranked = []
        for item in items:
            tm, airline, stops = _summary(item)
            score = 0
            if wanted_time and tm == wanted_time: score += 8
            if wanted_airline and airline == wanted_airline: score += 4
            if wanted_stops is not None and stops == int(wanted_stops): score += 2
            ranked.append((score, item))
        ranked.sort(key=lambda x: x[0], reverse=True)
        return ranked[0][1] if ranked and ranked[0][0] >= 8 else None

    token = None
    if personal and regenerate_itinerary and SERPAPI_API_KEY:
        try:
            departure = offer.get("departure_code") or offer.get("departure_airport")
            arrival = offer.get("arrival_code") or offer.get("arrival_airport")
            outbound_date = offer.get("outbound_date")
            return_date = offer.get("return_date")
            if departure and arrival and outbound_date and return_date:
                base = {"engine":"google_flights", "api_key":SERPAPI_API_KEY,
                        "departure_id":departure, "arrival_id":arrival,
                        "outbound_date":outbound_date, "return_date":return_date,
                        "type":"1", "hl":"en", "gl":"il", "currency":"ILS",
                        "travel_class":str(travel_class or "1"), "adults":str(pax_adults),
                        "children":str(pax_children), "bags":"0", "sort_by":"2",
                        "no_cache":"false"}
                out_data = requests.get("https://serpapi.com/search.json", params=base, timeout=25).json()
                outbound = _choose(_items(out_data), offer.get("departure_time"),
                                   offer.get("airline"), offer.get("stops"))
                departure_token = (outbound or {}).get("departure_token")
                if departure_token:
                    ret_params = dict(base)
                    ret_params["departure_token"] = departure_token
                    ret_data = requests.get("https://serpapi.com/search.json", params=ret_params, timeout=25).json()
                    inbound = _choose(_items(ret_data), offer.get("return_departure_time"),
                                      offer.get("return_airline") or offer.get("airline"),
                                      offer.get("return_stops"))
                    token = (inbound or {}).get("booking_token")
        except Exception:
            token = None

    if not token and not personal:
        token = offer.get("booking_token") or (offer.get("flight") or {}).get("booking_token")

    if token and SERPAPI_API_KEY:
        try:
            params = {"engine":"google_flights", "booking_token":token,
                      "api_key":SERPAPI_API_KEY, "hl":"en", "gl":"il",
                      "currency":"ILS", "adults":str(pax_adults),
                      "children":str(pax_children)}
            data = requests.get("https://serpapi.com/search.json", params=params, timeout=25).json()
            exact_supplier, direct_airline, approved_supplier = [], [], []
            for group in data.get("booking_options") or []:
                if group.get("separate_tickets"):
                    continue
                part = group.get("together") or {}
                req = part.get("booking_request") or {}
                if not req.get("url"):
                    continue
                supplier_norm = _norm(part.get("book_with"))
                candidate = (part, req)
                if preferred and supplier_norm == preferred:
                    exact_supplier.append(candidate)
                elif part.get("airline") is True and not _is_unreliable_direct(part):
                    direct_airline.append(candidate)
                elif supplier_norm in ACTIONABLE_BOOKING_SUPPLIERS:
                    approved_supplier.append(candidate)
            pool = exact_supplier or direct_airline or approved_supplier
            if pool:
                part, req = min(pool, key=lambda x: float(x[0].get("price") or 10**9))
                return BookerTarget(url=req.get("url"), fields=_request_fields(req),
                    supplier=part.get("book_with") or recommended,
                    mode="personal_exact_party_regenerated" if personal else "recommended_supplier_refreshed",
                    exact=True)
        except Exception:
            pass

    if stored_url and not personal:
        return BookerTarget(url=stored_url,
            fields=parse_qsl(stored_post, keep_blank_values=True) if stored_post else [],
            supplier=recommended, mode="stored_supplier_fallback", exact=False,
            note="יש לוודא באתר הספק את מספר הנוסעים והזמינות לפני התשלום.")

    airline_names = (
        recommended,
        offer.get("airline"),
        offer.get("return_airline"),
        (offer.get("flight") or {}).get("airline"),
    )

    # Bluebird uses AeroCRS. Prefer its supplier-side deeplink so the customer does
    # not need to type TLV/destination/dates/passenger count again.
    if personal and any(_norm(name) in BLUEBIRD_NAMES for name in airline_names):
        bluebird_url = _bluebird_deeplink(offer, pax_adults, pax_children)
        if bluebird_url:
            return BookerTarget(
                url=bluebird_url, fields=[], supplier="Bluebird Airways",
                mode="bluebird_aerocrs_deeplink", exact=True,
                note="היעד, התאריכים ומספר הנוסעים מולאו מראש באתר בלו בירד.",
            )

    for airline_name in airline_names:
        official_url = OFFICIAL_AIRLINE_BOOKING_FALLBACKS.get(_norm(airline_name))
        if official_url:
            note = (
                "אריאלה פתחה עבורכם את מסך ההזמנה של בלו בירד."
                if _norm(airline_name) in BLUEBIRD_NAMES
                else "הספק לא מאפשר כרגע העברה מלאה של פרטי ההזמנה. אריאלה פתחה את אתר הספק עצמו — לא את Google."
            )
            return BookerTarget(url=official_url, fields=[],
                supplier=str(airline_name or recommended), mode="official_airline_fallback",
                exact=False, note=note)

    supplier_homepage = _homepage(stored_url)
    if personal and supplier_homepage:
        return BookerTarget(url=supplier_homepage, fields=[], supplier=recommended,
            mode="supplier_homepage_manual_entry", exact=False,
            note="הספק לא מאפשר כרגע העברה מלאה של פרטי ההזמנה. אריאלה פתחה את אתר הספק עצמו — לא את Google.")

    # Never use the original Google Flights result URL as a customer booking fallback.
    # If we cannot identify the supplier itself, keep the customer on Ariella instead
    # of pretending that a Google page is the supplier booking page.
    return BookerTarget(url=None, fields=[], supplier=recommended,
        mode="personal_exact_booking_unavailable" if personal else "recommended_supplier_unavailable",
        exact=False,
        note=("הספק לא אפשר כרגע לפתוח את הטיסה כשהיא מלאה מראש עם מספר הנוסעים שבחרתם."
              if personal else "מסלול ההזמנה אצל הספק המומלץ אינו זמין כרגע."))
