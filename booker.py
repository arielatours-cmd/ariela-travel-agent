"""BOOKER — supplier-aware booking orchestration for Ariella.

BOOKER resolves the safest actionable handoff for the exact round-trip deal.
It does not purchase or submit payment for the customer.
"""

from __future__ import annotations
from dataclasses import dataclass
from urllib.parse import parse_qsl
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

OFFICIAL_AIRLINE_BOOKING_FALLBACKS = {
    "bluebird airways": "https://www.bluebirdair.com/",
    "blue bird airways": "https://www.bluebirdair.com/",
    "bluebird": "https://www.bluebirdair.com/",
    "air haifa": "https://www.airhaifa.com/",
    "airhaifa": "https://www.airhaifa.com/",
    "אייר חיפה": "https://www.airhaifa.com/",
}


def _norm(value) -> str:
    return str(value or "").strip().lower()


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
        # Fresh exact-party search: select the same outbound, expand its returns,
        # then select the same inbound. The resulting booking_token is now tied to
        # the requested passenger composition rather than the shared DB search.
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

    # A stored token belongs to the original scan party. It is safe only when no
    # passenger composition was supplied; never silently use a 1-adult token for
    # a customer who selected a different party.
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

    # Some airlines do not expose an actionable booking request through Google
    # Flights. Never bounce the customer back to Ariella after a booking click;
    # continue to the airline's official booking homepage as the final fallback.
    airline_names = (
        recommended,
        offer.get("airline"),
        offer.get("return_airline"),
        (offer.get("flight") or {}).get("airline"),
    )
    for airline_name in airline_names if not personal else ():
        official_url = OFFICIAL_AIRLINE_BOOKING_FALLBACKS.get(_norm(airline_name))
        if official_url:
            return BookerTarget(url=official_url, fields=[],
                supplier=str(airline_name or recommended), mode="official_airline_fallback",
                exact=False, note="יש לבחור באתר חברת התעופה את הטיסה ומספר הנוסעים.")

    # Every scanned offer normally carries the original Google Flights result
    # URL. It is less precise than a supplier deep-link, but remains actionable
    # and is preferable to silently returning the customer to the Deals page.
    search_url = offer.get("booking_url")
    if search_url and not personal:
        return BookerTarget(url=search_url, fields=[], supplier=recommended or "Google Flights",
            mode="search_results_fallback", exact=False,
            note="יש לבחור בתוצאות את הטיסה ולאשר את מספר הנוסעים.")

    return BookerTarget(url=None, fields=[], supplier=recommended,
        mode="personal_exact_booking_unavailable" if personal else "recommended_supplier_unavailable",
        exact=False,
        note=("הספק לא אפשר כרגע לפתוח את הטיסה כשהיא מלאה מראש עם מספר הנוסעים שבחרתם."
              if personal else "מסלול ההזמנה אצל הספק המומלץ אינו זמין כרגע."))
