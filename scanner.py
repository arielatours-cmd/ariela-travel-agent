import itertools
import os
from datetime import date, datetime, timedelta, timezone
import requests
import re
import time

from config import (
    AIRPORT_NAMES, DEPARTURE_AIRPORTS, DEPARTURE_OFFSETS_DAYS, DESTINATIONS,
    MAX_SEARCHES_PER_SCAN, CUSTOMER_SCAN_MAX_API_REQUESTS, SERPAPI_API_KEY, TRIP_LENGTHS_DAYS,
)
from database import (create_scan_run, finish_scan_run, get_setting, insert_offer, price_history_reference,
    set_setting, latest_scan_cycle_index, update_scan_progress, clear_scan_stop, scan_stop_requested)
from scoring import calculate_deal_score

SERPAPI_URL = "https://serpapi.com/search.json"
HEBREW_WEEKDAYS = {0: "יום שני", 1: "יום שלישי", 2: "יום רביעי", 3: "יום חמישי", 4: "יום שישי", 5: "שבת", 6: "יום ראשון"}



def _api_key() -> str:
    key = SERPAPI_API_KEY or os.getenv("SERPAPI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("SERPAPI_API_KEY is missing in Render Environment.")
    return key


def _date_with_weekday(value: str | None):
    if not value:
        return None
    dt = datetime.strptime(value, "%Y-%m-%d")
    return {"date": value, "weekday_he": HEBREW_WEEKDAYS[dt.weekday()], "display_he": f"{HEBREW_WEEKDAYS[dt.weekday()]}, {dt.strftime('%d.%m.%Y')}"}


def _sum_flight_minutes(segments: list[dict]):
    total = sum(s.get("duration") or 0 for s in segments)
    return total or None


def _airline_code(segment: dict) -> str | None:
    code = (segment.get("airline_code") or segment.get("marketing_airline_code") or "").strip().upper()
    if code:
        return code
    flight_number = str(segment.get("flight_number") or "").strip().upper()
    if flight_number:
        token = flight_number.split()[0].replace("-", "")
        if 2 <= len(token) <= 3 and token.isalnum():
            return token
    # Fallbacks for common carriers if the API omits the IATA code.
    airline = str(segment.get("airline") or "").strip().lower()
    common = {
        "wizz air": "W6", "arkia": "IZ", "israir": "6H", "israir airlines": "6H",
        "aegean": "A3", "aegean airlines": "A3", "el al": "LY",
        "bluebird airways": "BZ", "ryanair": "FR", "easyjet": "U2",
        "air france": "AF", "klm": "KL", "lufthansa": "LH", "ita airways": "AZ",
    }
    return common.get(airline)


def _airline_logo_url(segment: dict, item: dict | None = None) -> str | None:
    # SerpApi/Google may expose the logo either on the segment or itinerary.
    direct = segment.get("airline_logo") or ((item or {}).get("airline_logo"))
    if direct:
        return direct
    code = _airline_code(segment)
    if code:
        return f"https://www.gstatic.com/flights/airline_logos/70px/{code}.png"
    return None


def _summarize_flight(item: dict) -> dict:
    segments = item.get("flights") or []
    first, last = (segments[0] if segments else {}), (segments[-1] if segments else {})
    dep, arr = first.get("departure_airport") or {}, last.get("arrival_airport") or {}
    layovers = item.get("layovers") or []
    connections = [{"airport": x.get("name") or x.get("id") or "שדה ביניים", "duration_minutes": x.get("duration")} for x in layovers]
    total = item.get("total_duration")
    actual = _sum_flight_minutes(segments)
    if actual is None and isinstance(total, (int, float)):
        actual = max(0, total - sum(x.get("duration_minutes") or 0 for x in connections))
    return_summary = None
    return_segments = item.get("return_flights") or item.get("return_flight") or []
    if isinstance(return_segments, dict):
        return_segments = return_segments.get("flights") or []
    if return_segments:
        rf = return_segments[0] or {}
        rdep = rf.get("departure_airport") or {}
        return_summary = {
            "departure_time": rdep.get("time"),
            "departure_airport": rdep.get("id"),
        }
    return {
        "price": item.get("price"), "airline": first.get("airline"),
        "airline_logo": _airline_logo_url(first, item),
        "airline_code": _airline_code(first),
        "flight_number": first.get("flight_number"),
        "departure_airport": dep.get("id"), "departure_airport_name": AIRPORT_NAMES.get(dep.get("id"), dep.get("id")),
        "departure_time": dep.get("time"), "departure_date": str(dep.get("time") or "")[:10] or None, "arrival_airport": arr.get("id"),
        "arrival_airport_name": AIRPORT_NAMES.get(arr.get("id"), arr.get("id")), "arrival_time": arr.get("time"), "arrival_date": str(arr.get("time") or "")[:10] or None,
        "total_duration_minutes": total, "actual_flight_duration_minutes": actual, "stops": len(layovers),
        "is_direct": len(layovers) == 0, "connections": connections,
        "return_departure_time": (return_summary or {}).get("departure_time"),
        "return_departure_airport": (return_summary or {}).get("departure_airport"),
        "baggage": {
            # Do not assume baggage inclusions when Google/SerpApi did not provide them.
            "personal_item": {"included": None, "known": False, "price_each_way": None, "estimated": True},
            "carry_on_8kg": {"included": None, "known": False, "price_each_way": None, "estimated": True},
            "checked_bag_23kg": {"included": None, "known": False, "price_each_way": None, "estimated": True},
        },
    }


def _deal_analysis(data: dict, flight_prices: list[float] | None = None) -> dict:
    insights = data.get("price_insights") or {}
    lowest = insights.get("lowest_price")
    typical = insights.get("typical_price_range") or []
    level = str(insights.get("price_level") or "").lower()
    low = typical[0] if len(typical) >= 2 else None
    high = typical[1] if len(typical) >= 2 else None
    serp_discount = round((low - lowest) / low * 100, 1) if isinstance(lowest, (int, float)) and isinstance(low, (int, float)) and low > 0 else None

    prices = sorted(float(x) for x in (flight_prices or []) if isinstance(x, (int, float)))
    search_median = None
    if len(prices) >= 3:
        middle = len(prices) // 2
        search_median = prices[middle] if len(prices) % 2 else (prices[middle - 1] + prices[middle]) / 2

    return {
        "is_exceptional_deal": level == "low" or (serp_discount is not None and serp_discount >= 15),
        "price_level": level or None, "lowest_price": lowest,
        "typical_price_low": low, "typical_price_high": high,
        "below_typical_low_percent": serp_discount,
        "search_median": search_median,
        "search_sample_count": len(prices),
    }


def _apply_best_price_reference(analysis: dict, price: float) -> dict:
    """Attach the best defensible reference for THIS itinerary price.

    Customer-facing percentage claims are allowed only for Google Flights typical
    pricing or Ariella history with >=8 observations. The current search median is
    a ranking fallback only and is never presented as a period average.
    """
    analysis = dict(analysis)
    trusted = []
    typical_low = analysis.get("typical_price_low")
    if isinstance(typical_low, (int, float)) and typical_low > 0:
        trusted.append(((typical_low - price) / typical_low * 100, "serpapi_typical"))

    hist = analysis.get("historical_median")
    hist_n = int(analysis.get("historical_sample_count") or 0)
    if isinstance(hist, (int, float)) and hist > 0 and hist_n >= 8:
        trusted.append(((hist - price) / hist * 100, "history"))

    fallback = []
    search_median = analysis.get("search_median")
    search_n = int(analysis.get("search_sample_count") or 0)
    if isinstance(search_median, (int, float)) and search_median > 0 and search_n >= 5:
        fallback.append(((search_median - price) / search_median * 100, "search_distribution"))

    candidates = trusted or fallback
    analysis.pop("best_discount_percent", None)
    analysis.pop("price_reference_source", None)
    if candidates:
        discount, source = max(candidates, key=lambda x: x[0])
        analysis["best_discount_percent"] = round(discount, 1)
        analysis["price_reference_source"] = source
        analysis["price_reference_reliable"] = source in {"serpapi_typical", "history"}
    else:
        analysis["price_reference_reliable"] = False
    return analysis


def _serpapi_request(params: dict) -> dict:
    """SerpAPI request with bounded retry/backoff for transient 429/5xx errors."""
    last_error = None
    for attempt, delay in enumerate((0, 2, 5, 10), start=1):
        if delay:
            time.sleep(delay)
        try:
            response = requests.get(SERPAPI_URL, params=params, timeout=45)
            if response.status_code == 429 or 500 <= response.status_code < 600:
                last_error = RuntimeError(f"SerpAPI HTTP {response.status_code}")
                if attempt < 4:
                    continue
            response.raise_for_status()
            data = response.json()
            if data.get("error"):
                message = str(data["error"])
                if ("too many" in message.lower() or "rate" in message.lower()) and attempt < 4:
                    last_error = RuntimeError(message)
                    continue
                raise RuntimeError(message)
            return data
        except requests.RequestException as exc:
            last_error = exc
            if attempt >= 4:
                raise
    raise last_error or RuntimeError("SerpAPI request failed")


def _roundtrip_params(departure: str, arrival: str, outbound_date: str, return_date: str, adults: int = 1, children: int = 0) -> dict:
    return {
        "engine": "google_flights",
        "api_key": _api_key(),
        "departure_id": departure,
        "arrival_id": arrival,
        "outbound_date": outbound_date,
        "return_date": return_date,
        "type": "1",
        "hl": "en",
        "gl": "il",
        "currency": "ILS",
        "travel_class": "1",
        "adults": str(max(1, int(adults or 1))),
        "children": str(max(0, int(children or 0))),
        "bags": "0",
        "sort_by": "2",
        # Keep cache enabled. SerpApi cached searches within its cache window do not
        # consume the monthly search quota.
        "no_cache": "false",
    }



# Suppliers we are comfortable auto-selecting today. Direct airline booking is always approved.
# This list is deliberately conservative; it can be expanded from admin later.
APPROVED_BOOKING_SUPPLIERS = {
    "trip.com", "booking.com", "expedia", "lastminute.com"
}

def _supplier_is_approved(option: dict) -> bool:
    if option.get("airline") is True:
        return True
    name = str(option.get("book_with") or "").strip().lower()
    return name in APPROVED_BOOKING_SUPPLIERS

def _ils_price(option: dict):
    for local in option.get("local_prices") or []:
        if str(local.get("currency") or "").upper() == "ILS" and isinstance(local.get("price"), (int, float)):
            return float(local["price"])
    return float(option["price"]) if isinstance(option.get("price"), (int, float)) else None

def _extract_bag_number(text: str):
    # Google/SerpApi returns baggage policy strings such as "1st checked bag: 99-187".
    nums = re.findall(r'(?<!\w)(\d+(?:\.\d+)?)', str(text or "").replace(",", ""))
    if not nums:
        return None
    # Ignore ordinal "1st"; use the last monetary-looking number / high end of a range.
    vals = [float(x) for x in nums]
    return vals[-1]

def _roundtrip_baggage_estimate(booking_data: dict) -> dict:
    bp = booking_data.get("baggage_prices") or {}
    departing = bp.get("departing") or []
    returning = bp.get("returning") or []
    together = bp.get("together") or []

    def find(kind, rows):
        keys = ("carry-on", "carry on") if kind == "carry" else ("checked bag", "checked baggage")
        for row in rows:
            low = str(row).lower()
            if any(k in low for k in keys):
                if "free" in low:
                    return 0.0
                return _extract_bag_number(row)
        return None

    def total(kind):
        out = find(kind, departing)
        ret = find(kind, returning)
        if out is not None or ret is not None:
            if out is not None and ret is not None:
                # Conservative customer-facing total: use the higher directional
                # baggage fee for BOTH directions. This intentionally prefers
                # over-estimating rather than surprising the customer later.
                high = max(out, ret)
                return high * 2, (out != ret)
            # One directional price only: use it for both directions.
            one = out if out is not None else ret
            return one * 2, True
        both = find(kind, together)
        if both is not None:
            # "together" may describe the whole itinerary; don't double it blindly.
            return both, True
        return None, True

    carry, carry_est = total("carry")
    checked, checked_est = total("checked")
    return {
        "carry_on_roundtrip_ils": carry,
        "carry_on_estimated": carry_est,
        "checked_bag_roundtrip_ils": checked,
        "checked_bag_estimated": checked_est,
        "raw": bp,
    }

def enrich_booking_options(flight: dict, departure: str, arrival: str, outbound_date: str, return_date: str) -> tuple[dict, int]:
    token = flight.get("booking_token")
    if not token:
        return flight, 0
    params = _roundtrip_params(departure, arrival, outbound_date, return_date, adults=adults, children=children)
    params.pop("departure_token", None)
    params["booking_token"] = token
    data = _serpapi_request(params)

    # Google can return normal round-trip booking options and cheaper
    # "separate tickets booked together" options. Separate tickets are useful
    # for comparison, but Ariella never auto-selects them as the primary option.
    all_priced = []
    selectable_priced = []
    for group in data.get("booking_options") or []:
        together = group.get("together")
        if not isinstance(together, dict):
            continue
        price = _ils_price(together)
        if price is None:
            continue
        row = (together, price, bool(group.get("separate_tickets")))
        all_priced.append(row)
        if not row[2]:
            selectable_priced.append(row)

    approved = [(o,p,sep) for o,p,sep in selectable_priced if _supplier_is_approved(o)]
    direct = [(o,p,sep) for o,p,sep in selectable_priced if o.get("airline") is True]

    cheapest_any = min(all_priced, key=lambda x:x[1]) if all_priced else (None,None,False)
    cheapest_selectable = min(selectable_priced, key=lambda x:x[1]) if selectable_priced else (None,None,False)
    cheapest_approved = min(approved, key=lambda x:x[1]) if approved else (None,None,False)
    cheapest_direct = min(direct, key=lambda x:x[1]) if direct else (None,None,False)

    # Reliability/price balance:
    # 1) never auto-select separate tickets; 2) prefer direct airline booking
    # when it is within max(5%, ₪75) of the cheapest approved non-separate option.
    chosen = None
    chosen_price = None
    if cheapest_direct[0] is not None and cheapest_approved[0] is not None:
        direct_option, direct_price, _ = cheapest_direct
        approved_option, approved_price, _ = cheapest_approved
        tolerance = max(75.0, approved_price * 0.05)
        if direct_price <= approved_price + tolerance:
            chosen, chosen_price = direct_option, direct_price
        else:
            chosen, chosen_price = approved_option, approved_price
    elif cheapest_direct[0] is not None:
        chosen, chosen_price, _ = cheapest_direct
    elif cheapest_approved[0] is not None:
        chosen, chosen_price, _ = cheapest_approved
    elif cheapest_selectable[0] is not None:
        chosen, chosen_price, _ = cheapest_selectable

    flight = dict(flight)
    flight["booking_supplier"] = (chosen or {}).get("book_with")
    flight["booking_supplier_price_ils"] = chosen_price
    flight["booking_supplier_approved"] = bool(chosen and _supplier_is_approved(chosen))
    flight["booking_supplier_is_direct"] = bool(chosen and chosen.get("airline") is True)

    # Persist the exact booking hand-off for the selected round-trip option.
    # This lets "Go to booking" open the already-selected outbound + return
    # rather than sending the customer back to a generic search page.
    chosen_request = (chosen or {}).get("booking_request") or {}
    flight["booking_request_url"] = chosen_request.get("url")
    flight["booking_request_post_data"] = chosen_request.get("post_data")
    flight["cheapest_any_supplier"] = (cheapest_any[0] or {}).get("book_with")
    flight["cheapest_any_price_ils"] = cheapest_any[1]
    flight["cheapest_any_is_separate"] = bool(cheapest_any[2])
    flight["direct_supplier"] = (cheapest_direct[0] or {}).get("book_with")
    flight["direct_supplier_price_ils"] = cheapest_direct[1]
    flight["booking_options_checked"] = len(all_priced)

    # Explain a deliberate choice not to show the absolute cheapest option.
    reason_he = None
    reason_en = None
    if chosen_price is not None and cheapest_any[1] is not None and cheapest_any[1] < chosen_price:
        diff = int(round(chosen_price - cheapest_any[1]))
        if cheapest_any[2]:
            if flight["booking_supplier_is_direct"]:
                reason_he = f"נמצאה אפשרות זולה יותר ב־₪{diff}, אך היא כוללת כרטיסים נפרדים. אריאלה העדיפה הזמנה ישירה מחברת התעופה במחיר מעט גבוה יותר."
                reason_en = f"A cheaper option by ₪{diff} was found, but it uses separate tickets. Ariella preferred direct booking with the airline for a slightly higher price."
            else:
                reason_he = f"נמצאה אפשרות זולה יותר ב־₪{diff}, אך היא כוללת כרטיסים נפרדים. אריאלה העדיפה אפשרות הזמנה מאושרת ופשוטה יותר."
                reason_en = f"A cheaper option by ₪{diff} was found, but it uses separate tickets. Ariella preferred an approved, simpler booking option."
        elif flight["booking_supplier_is_direct"]:
            reason_he = f"נמצאה אפשרות זולה יותר ב־₪{diff} דרך ספק אחר. אריאלה העדיפה הזמנה ישירה מחברת התעופה כי פער המחיר קטן."
            reason_en = f"A cheaper option by ₪{diff} was found through another seller. Ariella preferred direct airline booking because the price difference is small."
        elif flight["booking_supplier_approved"]:
            reason_he = f"נמצאה אפשרות זולה יותר ב־₪{diff} אצל ספק שלא אושר. אריאלה העדיפה ספק מאושר במחיר מעט גבוה יותר."
            reason_en = f"A cheaper option by ₪{diff} was found with an unapproved seller. Ariella preferred an approved seller for a slightly higher price."
    flight["booking_choice_reason_he"] = reason_he
    flight["booking_choice_reason_en"] = reason_en

    baggage = _roundtrip_baggage_estimate(data)
    base_baggage = dict(flight.get("baggage") or {})
    carry = dict(base_baggage.get("carry_on_8kg") or {})
    checked = dict(base_baggage.get("checked_bag_23kg") or {})
    if baggage["carry_on_roundtrip_ils"] is not None:
        carry["roundtrip_price_ils"] = baggage["carry_on_roundtrip_ils"]
        carry["estimated"] = baggage["carry_on_estimated"]
        carry["known"] = True
        carry["included"] = baggage["carry_on_roundtrip_ils"] == 0
    if baggage["checked_bag_roundtrip_ils"] is not None:
        checked["roundtrip_price_ils"] = baggage["checked_bag_roundtrip_ils"]
        checked["estimated"] = baggage["checked_bag_estimated"]
        checked["known"] = True
        checked["included"] = baggage["checked_bag_roundtrip_ils"] == 0
    base_baggage["carry_on_8kg"] = carry
    base_baggage["checked_bag_23kg"] = checked
    flight["baggage"] = base_baggage
    return flight, 1


def search_flights(departure: str, arrival: str, outbound_date: str, return_date: str, max_outbounds: int | None = None, adults: int = 1, children: int = 0) -> dict:
    """Evaluate every outbound/return combination returned by Google Flights.

    First request gets all outbound choices. Each unique departure_token is then
    expanded to its return choices. We keep every complete combination so the
    caller can score the FULL round trip before choosing a winner.
    """
    params = _roundtrip_params(departure, arrival, outbound_date, return_date, adults=adults, children=children)
    outbound_data = _serpapi_request(params)
    api_requests = 1

    outbound_items = (outbound_data.get("best_flights") or []) + (outbound_data.get("other_flights") or [])
    outbound_items = [f for f in outbound_items if isinstance(f.get("price"), (int, float)) and f.get("departure_token")]

    # Deduplicate identical tokens while preserving Google's ranking.
    seen = set()
    unique_outbounds = []
    for item in outbound_items:
        token = item.get("departure_token")
        if token in seen:
            continue
        seen.add(token)
        unique_outbounds.append(item)

    # Cost control for broad discovery scans. Targeted/customer searches keep full depth.
    if max_outbounds is not None:
        unique_outbounds = unique_outbounds[:max(1, int(max_outbounds))]

    complete = []
    for outbound_item in unique_outbounds:
        outbound_summary = _summarize_flight(outbound_item)
        return_params = dict(params)
        return_params["departure_token"] = outbound_item["departure_token"]
        return_data = _serpapi_request(return_params)
        api_requests += 1
        return_items = (return_data.get("best_flights") or []) + (return_data.get("other_flights") or [])
        for inbound_item in return_items:
            if not isinstance(inbound_item.get("price"), (int, float)):
                continue
            inbound_summary = _summarize_flight(inbound_item)
            if not inbound_summary.get("departure_time") or not inbound_summary.get("arrival_time"):
                continue
            combo = dict(outbound_summary)
            combo["price"] = inbound_item.get("price")
            combo["return_departure_time"] = inbound_summary.get("departure_time")
            combo["return_arrival_time"] = inbound_summary.get("arrival_time")
            combo["return_arrival_date"] = inbound_summary.get("arrival_date")
            combo["return_airline"] = inbound_summary.get("airline")
            combo["return_airline_logo"] = inbound_summary.get("airline_logo")
            combo["return_stops"] = inbound_summary.get("stops")
            combo["return_connections"] = inbound_summary.get("connections") or []
            combo["return_total_duration_minutes"] = inbound_summary.get("total_duration_minutes")
            combo["booking_token"] = inbound_item.get("booking_token")
            complete.append(combo)

    combo_prices = [f.get("price") for f in complete if isinstance(f.get("price"), (int, float))]
    analysis = _deal_analysis(outbound_data, combo_prices)
    return {
        "route": f"{departure}-{arrival}",
        "departure_code": departure,
        "arrival_code": arrival,
        "departure_airport_name": AIRPORT_NAMES.get(departure, departure),
        "arrival_airport_name": AIRPORT_NAMES.get(arrival, arrival),
        "outbound": _date_with_weekday(outbound_date),
        "return": _date_with_weekday(return_date),
        "deal_analysis": analysis,
        "flights": complete,
        "booking_url": (outbound_data.get("search_metadata") or {}).get("google_flights_url"),
        "api_requests": api_requests,
        "combinations_checked": len(complete),
        "outbounds_checked": len(unique_outbounds),
    }

def _all_search_jobs() -> list[dict]:
    today = date.today()
    jobs = []
    destinations_by_code = {d["code"]: d for d in DESTINATIONS}
    # Interleave destinations so every small scan covers several countries, not one destination repeatedly.
    for offset, trip_length, departure, destination in itertools.product(DEPARTURE_OFFSETS_DAYS, TRIP_LENGTHS_DAYS, DEPARTURE_AIRPORTS, DESTINATIONS):
        outbound = today + timedelta(days=offset)
        ret = outbound + timedelta(days=trip_length)
        jobs.append({
            "departure": departure, "arrival": destination["code"], "outbound": outbound.isoformat(),
            "return": ret.isoformat(), "destination_name": destinations_by_code[destination["code"]]["name"],
            "country_flag": destinations_by_code[destination["code"]]["country_flag"],
        })
    return jobs


def _next_jobs(limit: int) -> list[dict]:
    jobs = _all_search_jobs()
    cursor = int(get_setting("scan_cursor", "0") or 0) % len(jobs)
    selected = [jobs[(cursor + i) % len(jobs)] for i in range(min(limit, len(jobs)))]
    set_setting("scan_cursor", str((cursor + len(selected)) % len(jobs)))
    return selected


def _run_jobs_scan(jobs: list[dict], max_outbounds_per_route: int | None = None, max_api_requests: int | None = None, scan_type: str = "general") -> dict:
    run_id = create_scan_run(len(jobs), scan_type=scan_type)
    clear_scan_stop()
    completed = offers_found = errors = api_requests = 0
    new_offers = existing_offers = 0
    error_messages: list[str] = []
    status_messages: list[str] = []

    try:
        for job in jobs:
            if scan_stop_requested():
                status_messages.append("הסריקה נעצרה ידנית")
                break
            if max_api_requests is not None and api_requests >= max_api_requests:
                status_messages.append(f"עצירת בטיחות: הגעה למגבלת {max_api_requests} בקשות API")
                break
            try:
                # Count every attempted destination. A timeout/error is still a completed
                # test slot, so a 30-destination scan can finish as 30/30 with errors
                # instead of appearing stuck at 24/30.
                completed += 1
                result = search_flights(job["departure"], job["arrival"], job["outbound"], job["return"], max_outbounds=max_outbounds_per_route)
                api_requests += int(result.get("api_requests") or 0)

                # Score COMPLETE round-trip combinations first; publish only the winner.
                scored_combinations = []
                for flight in result["flights"]:
                    if not flight.get("return_departure_time") or not flight.get("return_arrival_time"):
                        continue

                    analysis = dict(result["deal_analysis"])
                    price = float(flight["price"])
                    month = int(job["outbound"][5:7])
                    history = price_history_reference(job["departure"], job["arrival"], month, price)
                    analysis["historical_sample_count"] = history["sample_count"]
                    analysis["historical_median"] = history["median"]
                    analysis["historical_percentile"] = history["percentile"]
                    analysis = _apply_best_price_reference(analysis, price)

                    score = calculate_deal_score(analysis, flight)
                    scored_combinations.append((score["score"], -price, flight, analysis, score))

                if scored_combinations:
                    scored_combinations.sort(key=lambda x: (x[0], x[1]), reverse=True)
                    _, _, flight, analysis, score = scored_combinations[0]
                    flight, booking_requests = enrich_booking_options(
                        flight, job["departure"], job["arrival"], job["outbound"], job["return"]
                    )
                    api_requests += booking_requests
                    # Prefer the approved bookable price for what Ariella shows.
                    if isinstance(flight.get("booking_supplier_price_ils"), (int, float)):
                        flight["price"] = flight["booking_supplier_price_ils"]
                    analysis = _apply_best_price_reference(analysis, float(flight["price"]))
                    score = calculate_deal_score(analysis, flight)
                    analysis["combinations_checked"] = result.get("combinations_checked", len(scored_combinations))
                    analysis["outbounds_checked"] = result.get("outbounds_checked")
                    offer = {
                        "observed_at": datetime.now(timezone.utc).isoformat(),
                        "route": result["route"],
                        "departure_code": job["departure"],
                        "arrival_code": job["arrival"],
                        "departure_airport_name": result["departure_airport_name"],
                        "arrival_airport_name": result["arrival_airport_name"],
                        "destination_name": job["destination_name"],
                        "country_flag": job["country_flag"],
                        "outbound_date": job["outbound"],
                        "return_date": job["return"],
                        "outbound": result["outbound"],
                        "return": result["return"],
                        "deal_analysis": analysis,
                        "flight": flight,
                        "deal_score": score,
                        "booking_url": result["booking_url"],
                        "trip_id": job.get("trip_id"),
                    }
                    is_new = insert_offer(run_id, offer)
                    offers_found += 1
                    if is_new:
                        new_offers += 1
                    else:
                        existing_offers += 1
            except Exception as exc:
                errors += 1
                error_messages.append(f"{job['departure']}-{job['arrival']}: {exc}")
            finally:
                update_scan_progress(run_id, completed, offers_found, errors, api_requests)
    except BaseException as exc:
        # Still close the DB scan record if the worker/request fails unexpectedly.
        errors += 1
        error_messages.append(f"scan: {exc}")
        raise
    finally:
        finish_scan_run(
            run_id, completed, offers_found, errors,
            "; ".join(status_messages + error_messages)[:2000] or None, api_requests=api_requests
        )

    return {
        "status": "success" if errors == 0 else "partial",
        "scan_run_id": run_id,
        "searches_planned": len(jobs),
        "searches_completed": completed,
        "api_requests": api_requests,
        "offers_found": offers_found,
        "new_offers": new_offers,
        "existing_offers": existing_offers,
        "stopped": completed < len(jobs),
        "errors": errors,
        "error_messages": error_messages,
        "status_messages": status_messages,
    }



def run_hourly_scan(max_searches: int | None = None) -> dict:
    return _run_jobs_scan(_next_jobs(max_searches or MAX_SEARCHES_PER_SCAN), scan_type="hourly")


def _wide_search_jobs(limit: int | None = None) -> list[dict]:
    """One rotating vacation window per destination across the full six-month horizon."""
    today = date.today()
    max_items = min(limit or len(DESTINATIONS), len(DESTINATIONS))

    # Dense six-month coverage, not a handful of near-identical dates.
    offsets = [14, 21, 28, 35, 42, 49, 56, 63, 70, 77, 84, 91,
               105, 119, 133, 147, 161, 175]
    lengths = [3, 4, 5, 6, 7, 8, 10, 12, 14]

    # Every scan advances the destination/date pairing, so repeated wide scans
    # progressively cover different periods instead of repeating the same dates.
    try:
        cycle = latest_scan_cycle_index()
    except Exception:
        cycle = 0

    jobs = []
    origins = [str(x).upper() for x in DEPARTURE_AIRPORTS if x] or ["TLV"]
    for i, destination in enumerate(DESTINATIONS[:max_items]):
        j = i + cycle
        offset = offsets[j % len(offsets)]
        trip_length = lengths[(j // len(offsets) + i) % len(lengths)]
        outbound = today + timedelta(days=offset)
        ret = outbound + timedelta(days=trip_length)
        # Wide discovery must cover every configured Israeli departure airport.
        # This includes HFA as well as TLV; otherwise Haifa can never enter the DB.
        for origin in origins:
            jobs.append({
                "departure": origin,
                "arrival": destination["code"],
                "outbound": outbound.isoformat(),
                "return": ret.isoformat(),
                "destination_name": destination["name"],
                "country_flag": destination["country_flag"],
            })
    return jobs


def run_wide_scan(max_destinations: int | None = None) -> dict:
    limit = max(1, min(int(max_destinations or len(DESTINATIONS)), len(DESTINATIONS)))
    return _run_jobs_scan(_wide_search_jobs(limit), max_outbounds_per_route=3, max_api_requests=220, scan_type="wide")



SKI_DESTINATIONS = [
    {"code": "GVA", "name": "Geneva / Alps", "country_flag": "🇨🇭"},
    {"code": "ZRH", "name": "Zurich / Swiss Alps", "country_flag": "🇨🇭"},
    {"code": "MUC", "name": "Munich / Bavarian Alps", "country_flag": "🇩🇪"},
    {"code": "VIE", "name": "Vienna / Austrian ski regions", "country_flag": "🇦🇹"},
    {"code": "MXP", "name": "Milan / Italian Alps", "country_flag": "🇮🇹"},
    {"code": "SOF", "name": "Sofia / Bulgarian ski regions", "country_flag": "🇧🇬"},
]


def _customer_destination_codes(answers: dict) -> list[str]:
    """Parse one/several IATA codes, or a curated ski-airport set for ski mode."""
    raw = str(answers.get("destinations") or "").strip()
    if str(answers.get("vacation_type") or "") == "ski" and not raw:
        return [d["code"] for d in SKI_DESTINATIONS]
    aliases = {
        "רומא": "FCO", "rome": "FCO", "fco": "FCO",
        "אתונה": "ATH", "athens": "ATH", "ath": "ATH",
        "בודפשט": "BUD", "budapest": "BUD", "bud": "BUD",
        "פראג": "PRG", "prague": "PRG", "prg": "PRG",
        "וינה": "VIE", "vienna": "VIE", "vie": "VIE",
        "מילאנו": "MXP", "milan": "MXP", "mxp": "MXP",
        "לרנקה": "LCA", "larnaca": "LCA", "lca": "LCA",
        "סופיה": "SOF", "sofia": "SOF", "sof": "SOF",
        "פריז": "CDG", "paris": "CDG", "cdg": "CDG",
        "אמסטרדם": "AMS", "amsterdam": "AMS", "ams": "AMS",
        "ברצלונה": "BCN", "barcelona": "BCN", "bcn": "BCN",
        "מדריד": "MAD", "madrid": "MAD", "mad": "MAD",
        "ליסבון": "LIS", "lisbon": "LIS", "lis": "LIS",
        "לונדון": "LHR", "london": "LHR", "lhr": "LHR",
        "ברלין": "BER", "berlin": "BER", "ber": "BER",
        "מינכן": "MUC", "munich": "MUC", "muc": "MUC",
        "ציריך": "ZRH", "zurich": "ZRH", "zrh": "ZRH",
        "בוקרשט": "OTP", "bucharest": "OTP", "otp": "OTP",
        "קרקוב": "KRK", "krakow": "KRK", "krk": "KRK",
        "ורשה": "WAW", "warsaw": "WAW", "waw": "WAW",
        "טביליסי": "TBS", "tbilisi": "TBS", "tbs": "TBS",
        "בנגקוק": "BKK", "bangkok": "BKK", "bkk": "BKK",
        "ניו יורק": "JFK", "new york": "JFK", "jfk": "JFK",
    }
    supported = {d["code"] for d in DESTINATIONS} | {d["code"] for d in SKI_DESTINATIONS}
    codes = []
    for token in [x.strip() for x in re.split(r"[,;/]+", raw) if x.strip()]:
        code = aliases.get(token.lower())
        if not code and len(token) == 3 and token.isalpha():
            code = token.upper()
        if code and len(code) == 3 and code.isalpha() and code not in codes:
            # Airport picker already resolves valid IATA codes. Do not limit customer
            # searches to Ariella's curated discovery list.
            codes.append(code.upper())
    return codes


def _customer_scan_rank(score: dict, answers: dict) -> float:
    """Use a destination-fit score when the customer already chose where to go."""
    if str(answers.get("destination_mode") or "open") not in {"specific", "several"}:
        return float(score.get("score") or 0)
    c = score.get("components") or {}
    return (
        float(c.get("route") or 0) * 2.0
        + float(c.get("time_value") or c.get("hours") or 0) * 2.0
        + float(c.get("baggage") or 0) * 1.5
        + float(c.get("price") or 0) * 0.5
        + float(c.get("rarity") or 0) * 0.25
    )


def run_customer_trip_search(trip_id: int, answers: dict) -> dict:
    """Run a targeted fresh search for the customer's chosen vacation.

    A chosen destination is a relevance search, not a global bargain contest: valid
    flights are therefore retained even when their global deal score is below 65.
    """
    arrivals = _customer_destination_codes(answers)
    vacation_type = str(answers.get("vacation_type") or "standard")
    if answers.get("_alternative_other_destination"):
        original = set(arrivals)
        arrivals = [d["code"] for d in DESTINATIONS if d["code"] not in original]
    elif not arrivals and vacation_type == "standard" and str(answers.get("destination_mode") or "open") == "open":
        # Ariella chooses: search the curated discovery universe instead of
        # returning unsupported_destination when the shared DB has no match.
        arrivals = [d["code"] for d in DESTINATIONS]
    if not arrivals:
        return {"status": "unsupported_destination", "offers_found": 0, "api_requests": 0}

    origins = [str(x).upper() for x in answers.get("origin_airports", []) if x] or list(DEPARTURE_AIRPORTS)
    date_mode = answers.get("date_mode")
    jobs = []
    ski_mode = vacation_type == "ski"
    if date_mode == "exact" and answers.get("departure_date") and answers.get("return_date"):
        business_mode = str(answers.get("vacation_type") or "") == "business"
        try:
            flex_key = "business_flex_days" if business_mode else "date_flex_days"
            flex_days = max(0, min(3, int(answers.get(flex_key) or 0)))
        except (TypeError, ValueError):
            flex_days = 0
        base_out = datetime.strptime(answers["departure_date"], "%Y-%m-%d").date()
        base_ret = datetime.strptime(answers["return_date"], "%Y-%m-%d").date()
        offsets = range(-flex_days, flex_days + 1) if flex_days else [0]
        if business_mode and not flex_days and answers.get("business_arrive_by_time"):
            offsets = [-1, 0]
        # Regular initial exact-date searches deliberately scan representative
        # windows across the entire requested month. This both serves the exact
        # request and grows fresh shared inventory. The explicit "other destination,
        # same dates" second chance remains exact and never changes the dates.
        scan_whole_month = (
            vacation_type == "standard"
            and not answers.get("_alternative_other_destination")
        )
        if scan_whole_month:
            trip_len = max(1, (base_ret - base_out).days)
            month_first = base_out.replace(day=1)
            candidate_starts = [base_out]
            for day_offset in (2, 9, 16, 23):
                candidate = month_first + timedelta(days=day_offset)
                if candidate.month == month_first.month and candidate not in candidate_starts:
                    candidate_starts.append(candidate)
            candidate_starts.sort(key=lambda d: (0 if d == base_out else 1, abs((d - base_out).days)))
            for arrival in arrivals:
                for origin in origins:
                    for start in candidate_starts:
                        ret_date = start + timedelta(days=trip_len)
                        jobs.append({"departure": origin, "arrival": arrival, "outbound": start.isoformat(), "return": ret_date.isoformat()})
        elif flex_days:
            # A flexible request means each requested date may move within the chosen
            # tolerance. Interleave origins so TLV/HFA both get searched before the
            # safety cap is reached, and prioritize the smallest changes first.
            pairs = [(a, b) for a in offsets for b in offsets]
            pairs.sort(key=lambda pair: (abs(pair[0]) + abs(pair[1]), abs(pair[0] - pair[1]), abs(pair[0]), abs(pair[1])))
            for out_offset, ret_offset in pairs:
                out_date = base_out + timedelta(days=out_offset)
                ret_date = base_ret + timedelta(days=ret_offset)
                if ret_date <= out_date:
                    continue
                for arrival in arrivals:
                    for origin in origins:
                        jobs.append({"departure": origin, "arrival": arrival, "outbound": out_date.isoformat(), "return": ret_date.isoformat()})
        else:
            for arrival in arrivals:
                for origin in origins:
                    out_date = base_out
                    ret_date = base_ret
                    if ret_date <= out_date:
                        continue
                    jobs.append({"departure": origin, "arrival": arrival, "outbound": out_date.isoformat(), "return": ret_date.isoformat()})
    elif ski_mode and date_mode == "ski_flexible":
        # Use the next core ski season and keep the first live test controlled:
        # two representative 6-night windows per airport/origin, not a world-wide explosion.
        today_date = datetime.now(timezone.utc).date()
        season_year = today_date.year if today_date.month <= 2 else today_date.year + 1
        candidates = [date(season_year, 1, 11), date(season_year, 2, 8)]
        for arrival in arrivals:
            for origin in origins:
                for start in candidates:
                    if start <= today_date:
                        continue
                    jobs.append({"departure": origin, "arrival": arrival, "outbound": start.isoformat(), "return": (start + timedelta(days=6)).isoformat()})
    else:
        outbound_month = str(answers.get("outbound_month") or answers.get("travel_month") or "")[:7]
        return_month = str(answers.get("return_month") or outbound_month)[:7]
        if not outbound_month or not return_month:
            return {"status": "missing_dates", "offers_found": 0, "api_requests": 0}
        out_first = datetime.strptime(outbound_month + "-01", "%Y-%m-%d").date()
        ret_first = datetime.strptime(return_month + "-01", "%Y-%m-%d").date()
        if ski_mode:
            # For ski searches, test two representative departure points in the chosen month.
            # This keeps API consumption predictable while comparing several ski gateways.
            out_starts = [out_first + timedelta(days=d) for d in (7, 17)]
            for arrival in arrivals:
                for origin in origins:
                    for start in out_starts:
                        if start.month != out_first.month:
                            continue
                        ret = start + timedelta(days=6)
                        if ret.month != ret_first.month and ret_first.month != out_first.month:
                            ret = ret_first + timedelta(days=9)
                        if ret <= start or ret.month != ret_first.month:
                            continue
                        jobs.append({"departure": origin, "arrival": arrival, "outbound": start.isoformat(), "return": ret.isoformat()})
        else:
            if answers.get("_alternative_nearby_dates"):
                # Explicit "same destination, other dates": widen beyond the initial
                # ±1-month display cap, while preserving the requested trip shape.
                out_months = [m for m in (answers.get("_alternative_outbound_months") or answers.get("_alternative_months") or [outbound_month]) if m]
                ret_months = [m for m in (answers.get("_alternative_return_months") or answers.get("_alternative_months") or [return_month]) if m]
                try:
                    trip_len = max(2, min(21, int(answers.get("_requested_trip_length_days") or 7)))
                except (TypeError, ValueError):
                    trip_len = 7
                allowed_ret = set(str(m)[:7] for m in ret_months)
                for month_value in out_months[:3]:
                    try:
                        month_first = datetime.strptime(str(month_value)[:7] + "-01", "%Y-%m-%d").date()
                    except Exception:
                        continue
                    out_starts = [month_first + timedelta(days=d) for d in (3, 10, 17, 24)]
                    for arrival in arrivals:
                        for origin in origins:
                            for start in out_starts:
                                if start.month != month_first.month:
                                    continue
                                ret = start + timedelta(days=trip_len)
                                if ret.strftime("%Y-%m") not in allowed_ret:
                                    continue
                                jobs.append({"departure": origin, "arrival": arrival, "outbound": start.isoformat(), "return": ret.isoformat()})
            else:
                out_starts = [out_first + timedelta(days=d) for d in (3, 10, 17, 24)]
                ret_starts = [ret_first + timedelta(days=d) for d in (3, 10, 17, 24)]
                for arrival in arrivals:
                    for origin in origins:
                        for start in out_starts:
                            if start.month != out_first.month:
                                continue
                            for ret in ret_starts:
                                if ret <= start or ret.month != ret_first.month:
                                    continue
                                jobs.append({"departure": origin, "arrival": arrival, "outbound": start.isoformat(), "return": ret.isoformat()})

    run_id = create_scan_run(len(jobs), scan_type=f"personal_{str(answers.get('vacation_type') or 'standard')}", trip_id=trip_id)
    clear_scan_stop()
    completed = offers_found = errors = api_requests = 0
    new_offers = existing_offers = 0
    messages = []
    max_api_requests = max(1, CUSTOMER_SCAN_MAX_API_REQUESTS)
    destination_led = str(answers.get("destination_mode") or "open") in {"specific", "several"} or ski_mode
    destination_names = {d["code"]: d for d in (list(DESTINATIONS) + list(SKI_DESTINATIONS))}
    try:
        for job in jobs:
            if scan_stop_requested():
                messages.append("הסריקה נעצרה ידנית")
                break
            if max_api_requests is not None and api_requests >= max_api_requests:
                messages.append(f"עצירת בטיחות: הגעה למגבלת {max_api_requests} בקשות API")
                break
            try:
                # Price cards remain strictly per person. Group-seat availability is not
                # promised by Google Flights/SerpAPI, so the UI carries a supplier
                # verification notice for multi-passenger requests instead.
                result = search_flights(job["departure"], job["arrival"], job["outbound"], job["return"])
                api_requests += int(result.get("api_requests") or 0)
                completed += 1
                scored = []
                for flight in result["flights"]:
                    if not flight.get("return_departure_time") or not flight.get("return_arrival_time"):
                        continue
                    analysis = dict(result["deal_analysis"])
                    price = float(flight["price"])
                    month_no = int(job["outbound"][5:7])
                    history = price_history_reference(job["departure"], job["arrival"], month_no, price)
                    analysis.update({
                        "historical_sample_count": history["sample_count"],
                        "historical_median": history["median"],
                        "historical_percentile": history["percentile"],
                    })
                    analysis = _apply_best_price_reference(analysis, price)
                    score = calculate_deal_score(analysis, flight)
                    # Every complete valid result expands the shared DB. The 70+
                    # rule belongs only to the public Deals page, not persistence.
                    scored.append((_customer_scan_rank(score, answers), score["score"], -price, flight, analysis, score))
                if scored:
                    scored.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
                    dest = destination_names.get(job["arrival"], {})
                    # Persist every valid round-trip found by an external personal
                    # scan.  The first candidate is enriched for immediate display;
                    # the remaining candidates still expand the shared 48h DB and
                    # can match another customer's dates, budget or preferences.
                    for candidate_index, (_, _, _, flight, analysis, score) in enumerate(scored):
                        flight = dict(flight)
                        analysis = dict(analysis)
                        score = dict(score)
                        if candidate_index == 0:
                            flight, booking_requests = enrich_booking_options(
                                flight, job["departure"], job["arrival"], job["outbound"], job["return"]
                            )
                            api_requests += booking_requests
                            if isinstance(flight.get("booking_supplier_price_ils"), (int, float)):
                                flight["price"] = flight["booking_supplier_price_ils"]
                            analysis = _apply_best_price_reference(analysis, float(flight["price"]))
                            score = calculate_deal_score(analysis, flight)
                        insert_offer(run_id, {
                            "observed_at": datetime.now(timezone.utc).isoformat(),
                            "route": result["route"], "departure_code": job["departure"], "arrival_code": job["arrival"],
                            "departure_airport_name": result["departure_airport_name"], "arrival_airport_name": result["arrival_airport_name"],
                            "destination_name": dest.get("name") or job["arrival"], "country_flag": dest.get("country_flag") or "",
                            "outbound_date": job["outbound"], "return_date": job["return"],
                            "outbound": result["outbound"], "return": result["return"],
                            "deal_analysis": analysis, "flight": flight, "deal_score": score,
                            "booking_url": result["booking_url"], "trip_id": trip_id,
                            "inventory_scope": "shared", "source_trip_id": trip_id,
                            "candidate_rank": candidate_index + 1,
                        })
                        offers_found += 1
            except Exception as exc:
                errors += 1
                messages.append(f"{job['departure']}-{job['arrival']}: {exc}")
            finally:
                update_scan_progress(run_id, completed, offers_found, errors, api_requests)
    finally:
        finish_scan_run(run_id, completed, offers_found, errors, "; ".join(messages)[:2000] or None, api_requests=api_requests)
    return {"status": "success" if errors == 0 else "partial", "scan_run_id": run_id, "searches_completed": completed, "api_requests": api_requests, "offers_found": offers_found, "errors": errors}


def run_destination_scan(arrival_code: str, max_searches: int = 3) -> dict:
    arrival_code = str(arrival_code or "").upper().strip()
    allowed = {d["code"] for d in DESTINATIONS}
    if arrival_code not in allowed:
        return {"status": "error", "message": "Unsupported destination", "arrival_code": arrival_code}
    jobs = [j for j in _all_search_jobs() if j["arrival"] == arrival_code][:max(1, min(int(max_searches), 8))]
    run_id = create_scan_run(len(jobs), scan_type="destination")
    clear_scan_stop()
    completed = offers_found = errors = api_requests = 0
    new_offers = existing_offers = 0
    messages = []
    max_api_requests = 24
    try:
        for job in jobs:
            if scan_stop_requested():
                messages.append("הסריקה נעצרה ידנית")
                break
            if max_api_requests is not None and api_requests >= max_api_requests:
                messages.append(f"עצירת בטיחות: הגעה למגבלת {max_api_requests} בקשות API")
                break
            try:
                result = search_flights(job["departure"], job["arrival"], job["outbound"], job["return"])
                api_requests += int(result.get("api_requests") or 0)
                completed += 1
                scored = []
                for flight in result["flights"]:
                    if not flight.get("return_departure_time") or not flight.get("return_arrival_time"):
                        continue
                    analysis = dict(result["deal_analysis"])
                    price = float(flight["price"])
                    month = int(job["outbound"][5:7])
                    history = price_history_reference(job["departure"], job["arrival"], month, price)
                    analysis.update({
                        "historical_sample_count": history["sample_count"],
                        "historical_median": history["median"],
                        "historical_percentile": history["percentile"],
                    })
                    analysis = _apply_best_price_reference(analysis, price)
                    score=calculate_deal_score(analysis,flight)
                    scored.append((score["score"],-price,flight,analysis,score))
                if scored:
                    scored.sort(key=lambda x:(x[0],x[1]),reverse=True)
                    _,_,flight,analysis,score=scored[0]
                    flight, booking_requests = enrich_booking_options(
                        flight, job["departure"], job["arrival"], job["outbound"], job["return"]
                    )
                    api_requests += booking_requests
                    if isinstance(flight.get("booking_supplier_price_ils"), (int,float)):
                        flight["price"]=flight["booking_supplier_price_ils"]
                    analysis = _apply_best_price_reference(analysis, float(flight["price"]))
                    score = calculate_deal_score(analysis, flight)
                    insert_offer(run_id,{
                        "observed_at":datetime.now(timezone.utc).isoformat(),
                        "route":result["route"],"departure_code":job["departure"],"arrival_code":job["arrival"],
                        "departure_airport_name":result["departure_airport_name"],"arrival_airport_name":result["arrival_airport_name"],
                        "destination_name":job["destination_name"],"country_flag":job["country_flag"],
                        "outbound_date":job["outbound"],"return_date":job["return"],
                        "outbound":result["outbound"],"return":result["return"],
                        "deal_analysis":analysis,"flight":flight,"deal_score":score,
                        "booking_url":result["booking_url"],
                    })
                    offers_found += 1
            except Exception as exc:
                errors += 1
                messages.append(f"{job['departure']}-{job['arrival']}: {exc}")
    finally:
        finish_scan_run(run_id,completed,offers_found,errors,"; ".join(messages)[:2000] or None, api_requests=api_requests)
    return {"status":"success" if errors==0 else "partial","scan_run_id":run_id,"destination":arrival_code,
            "searches_completed":completed,"api_requests":api_requests,"offers_found":offers_found,"errors":errors}
