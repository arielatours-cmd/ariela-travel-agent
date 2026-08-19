import itertools
import os
from datetime import date, datetime, timedelta, timezone
import requests
import re

from config import (
    AIRPORT_NAMES, DEPARTURE_AIRPORTS, DEPARTURE_OFFSETS_DAYS, DESTINATIONS,
    MAX_SEARCHES_PER_SCAN, SERPAPI_API_KEY, TRIP_LENGTHS_DAYS,
)
from database import create_scan_run, finish_scan_run, get_setting, insert_offer, price_history_reference, set_setting
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
        "departure_time": dep.get("time"), "arrival_airport": arr.get("id"),
        "arrival_airport_name": AIRPORT_NAMES.get(arr.get("id"), arr.get("id")), "arrival_time": arr.get("time"),
        "total_duration_minutes": total, "actual_flight_duration_minutes": actual, "stops": len(layovers),
        "is_direct": len(layovers) == 0, "connections": connections,
        "return_departure_time": (return_summary or {}).get("departure_time"),
        "return_departure_airport": (return_summary or {}).get("departure_airport"),
        "baggage": {
            "personal_item": {"included": True, "price_each_way": 0, "estimated": True},
            "carry_on_8kg": {"included": False, "price_each_way": None, "estimated": True},
            "checked_bag_23kg": {"included": False, "price_each_way": None, "estimated": True},
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
    }


def _serpapi_request(params: dict) -> dict:
    response = requests.get(SERPAPI_URL, params=params, timeout=60)
    response.raise_for_status()
    data = response.json()
    if data.get("error"):
        raise RuntimeError(data["error"])
    return data


def _roundtrip_params(departure: str, arrival: str, outbound_date: str, return_date: str) -> dict:
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
        "adults": "1",
        "children": "0",
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
                return out + ret, False
            # One directional price only: show a clearly marked round-trip estimate x2.
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
    params = _roundtrip_params(departure, arrival, outbound_date, return_date)
    params.pop("departure_token", None)
    params["booking_token"] = token
    data = _serpapi_request(params)

    flattened = []
    for group in data.get("booking_options") or []:
        together = group.get("together")
        if isinstance(together, dict):
            flattened.append(together)
        # Separate tickets are not auto-selected as the primary booking option.
    priced = [(o, _ils_price(o)) for o in flattened]
    priced = [(o,p) for o,p in priced if p is not None]
    approved = [(o,p) for o,p in priced if _supplier_is_approved(o)]
    direct = [(o,p) for o,p in priced if o.get("airline") is True]

    cheapest_any = min(priced, key=lambda x:x[1]) if priced else (None,None)
    cheapest_approved = min(approved, key=lambda x:x[1]) if approved else (None,None)
    cheapest_direct = min(direct, key=lambda x:x[1]) if direct else (None,None)

    # Choose the best booking option, balancing reliability and price:
    # - Never auto-prefer an unapproved third-party supplier when an approved option exists.
    # - Prefer direct airline booking when it costs no more than 5% or ₪75 above
    #   the cheapest approved third-party option.
    # - Otherwise choose the cheapest approved option.
    # - Fall back to the cheapest available option only when no approved/direct option exists.
    chosen = None
    chosen_price = None
    if cheapest_direct[0] is not None and cheapest_approved[0] is not None:
        direct_option, direct_price = cheapest_direct
        approved_option, approved_price = cheapest_approved
        tolerance = max(75.0, approved_price * 0.05)
        if direct_price <= approved_price + tolerance:
            chosen, chosen_price = direct_option, direct_price
        else:
            chosen, chosen_price = approved_option, approved_price
    elif cheapest_direct[0] is not None:
        chosen, chosen_price = cheapest_direct
    elif cheapest_approved[0] is not None:
        chosen, chosen_price = cheapest_approved
    else:
        chosen, chosen_price = cheapest_any

    flight = dict(flight)
    flight["booking_supplier"] = (chosen or {}).get("book_with")
    flight["booking_supplier_price_ils"] = chosen_price
    flight["booking_supplier_approved"] = bool(chosen and _supplier_is_approved(chosen))
    flight["cheapest_any_supplier"] = (cheapest_any[0] or {}).get("book_with")
    flight["cheapest_any_price_ils"] = cheapest_any[1]
    flight["direct_supplier"] = (cheapest_direct[0] or {}).get("book_with")
    flight["direct_supplier_price_ils"] = cheapest_direct[1]
    flight["booking_options_checked"] = len(priced)

    baggage = _roundtrip_baggage_estimate(data)
    base_baggage = dict(flight.get("baggage") or {})
    carry = dict(base_baggage.get("carry_on_8kg") or {})
    checked = dict(base_baggage.get("checked_bag_23kg") or {})
    if baggage["carry_on_roundtrip_ils"] is not None:
        carry["roundtrip_price_ils"] = baggage["carry_on_roundtrip_ils"]
        carry["estimated"] = baggage["carry_on_estimated"]
    if baggage["checked_bag_roundtrip_ils"] is not None:
        checked["roundtrip_price_ils"] = baggage["checked_bag_roundtrip_ils"]
        checked["estimated"] = baggage["checked_bag_estimated"]
    base_baggage["carry_on_8kg"] = carry
    base_baggage["checked_bag_23kg"] = checked
    flight["baggage"] = base_baggage
    return flight, 1


def search_flights(departure: str, arrival: str, outbound_date: str, return_date: str) -> dict:
    """Evaluate every outbound/return combination returned by Google Flights.

    First request gets all outbound choices. Each unique departure_token is then
    expanded to its return choices. We keep every complete combination so the
    caller can score the FULL round trip before choosing a winner.
    """
    params = _roundtrip_params(departure, arrival, outbound_date, return_date)
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


def run_hourly_scan(max_searches: int | None = None) -> dict:
    jobs = _next_jobs(max_searches or MAX_SEARCHES_PER_SCAN)
    run_id = create_scan_run(len(jobs))
    completed = offers_found = errors = api_requests = 0
    error_messages: list[str] = []

    try:
        for job in jobs:
            try:
                result = search_flights(job["departure"], job["arrival"], job["outbound"], job["return"])
                api_requests += int(result.get("api_requests") or 0)
                completed += 1

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

                    candidates = []
                    if isinstance(analysis.get("below_typical_low_percent"), (int, float)):
                        candidates.append((analysis["below_typical_low_percent"], "serpapi_typical"))
                    if isinstance(history.get("median"), (int, float)) and history["median"] > 0:
                        candidates.append(((history["median"] - price) / history["median"] * 100, "history"))
                    search_median = analysis.get("search_median")
                    if isinstance(search_median, (int, float)) and search_median > 0:
                        candidates.append(((search_median - price) / search_median * 100, "search_distribution"))
                    if candidates:
                        best_discount, source = max(candidates, key=lambda item: item[0])
                        analysis["best_discount_percent"] = round(best_discount, 1)
                        analysis["price_reference_source"] = source

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
                    insert_offer(run_id, offer)
                    offers_found += 1
            except Exception as exc:
                errors += 1
                error_messages.append(f"{job['departure']}-{job['arrival']}: {exc}")
    except BaseException as exc:
        # Still close the DB scan record if the worker/request fails unexpectedly.
        errors += 1
        error_messages.append(f"scan: {exc}")
        raise
    finally:
        finish_scan_run(
            run_id, completed, offers_found, errors,
            "; ".join(error_messages)[:2000] or None
        )

    return {
        "status": "success" if errors == 0 else "partial",
        "scan_run_id": run_id,
        "searches_planned": len(jobs),
        "searches_completed": completed,
        "api_requests": api_requests,
        "offers_found": offers_found,
        "errors": errors,
        "error_messages": error_messages,
    }


def run_customer_trip_search(trip_id: int, answers: dict) -> dict:
    """Run a targeted fresh search only after the database has no suitable customer deal."""
    destinations = str(answers.get("destinations") or "").strip().lower()
    destination_aliases = {
        "רומא": "FCO", "rome": "FCO", "fco": "FCO",
        "אתונה": "ATH", "athens": "ATH", "ath": "ATH",
        "בודפשט": "BUD", "budapest": "BUD", "bud": "BUD",
        "פראג": "PRG", "prague": "PRG", "prg": "PRG",
        "וינה": "VIE", "vienna": "VIE", "vie": "VIE",
        "מילאנו": "MXP", "milan": "MXP", "mxp": "MXP",
    }
    arrival = destination_aliases.get(destinations)
    if not arrival:
        return {"status": "unsupported_destination", "offers_found": 0, "api_requests": 0}

    origins = [str(x).upper() for x in (answers.get("origin_airports") or DEPARTURE_AIRPORTS)]
    date_mode = answers.get("date_mode")
    jobs = []
    if date_mode == "exact" and answers.get("departure_date") and answers.get("return_date"):
        for origin in origins:
            jobs.append({"departure": origin, "arrival": arrival, "outbound": answers["departure_date"], "return": answers["return_date"]})
    else:
        # Month search: a few representative windows, deliberately bounded to protect API quota.
        month = str(answers.get("travel_month") or "")
        if not month:
            return {"status": "missing_dates", "offers_found": 0, "api_requests": 0}
        first = datetime.strptime(month + "-01", "%Y-%m-%d").date()
        starts = [first + timedelta(days=d) for d in (3, 10, 17, 24)]
        for origin in origins:
            for start in starts:
                if start.month == first.month:
                    jobs.append({"departure": origin, "arrival": arrival, "outbound": start.isoformat(), "return": (start + timedelta(days=4)).isoformat()})

    run_id = create_scan_run(len(jobs))
    completed = offers_found = errors = api_requests = 0
    messages = []
    try:
        for job in jobs:
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
                    month_no = int(job["outbound"][5:7])
                    history = price_history_reference(job["departure"], job["arrival"], month_no, price)
                    analysis.update({
                        "historical_sample_count": history["sample_count"],
                        "historical_median": history["median"],
                        "historical_percentile": history["percentile"],
                    })
                    candidates = []
                    if isinstance(analysis.get("below_typical_low_percent"), (int, float)):
                        candidates.append((analysis["below_typical_low_percent"], "serpapi_typical"))
                    if isinstance(history.get("median"), (int, float)) and history["median"] > 0:
                        candidates.append(((history["median"] - price) / history["median"] * 100, "history"))
                    if isinstance(analysis.get("search_median"), (int, float)) and analysis["search_median"] > 0:
                        candidates.append(((analysis["search_median"] - price) / analysis["search_median"] * 100, "search_distribution"))
                    if candidates:
                        discount, source = max(candidates, key=lambda x: x[0])
                        analysis["best_discount_percent"] = round(discount, 1)
                        analysis["price_reference_source"] = source
                    score = calculate_deal_score(analysis, flight)
                    if score["score"] >= 65:
                        scored.append((score["score"], -price, flight, analysis, score))
                if scored:
                    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
                    _, _, flight, analysis, score = scored[0]
                    flight, booking_requests = enrich_booking_options(
                        flight, job["departure"], job["arrival"], job["outbound"], job["return"]
                    )
                    api_requests += booking_requests
                    if isinstance(flight.get("booking_supplier_price_ils"), (int, float)):
                        flight["price"] = flight["booking_supplier_price_ils"]
                    insert_offer(run_id, {
                        "observed_at": datetime.now(timezone.utc).isoformat(),
                        "route": result["route"], "departure_code": job["departure"], "arrival_code": job["arrival"],
                        "departure_airport_name": result["departure_airport_name"], "arrival_airport_name": result["arrival_airport_name"],
                        "destination_name": destinations or arrival, "country_flag": "🇮🇹" if arrival == "FCO" else "",
                        "outbound_date": job["outbound"], "return_date": job["return"],
                        "outbound": result["outbound"], "return": result["return"],
                        "deal_analysis": analysis, "flight": flight, "deal_score": score,
                        "booking_url": result["booking_url"], "trip_id": trip_id,
                    })
                    offers_found += 1
            except Exception as exc:
                errors += 1
                messages.append(f"{job['departure']}-{job['arrival']}: {exc}")
    finally:
        finish_scan_run(run_id, completed, offers_found, errors, "; ".join(messages)[:2000] or None)
    return {"status": "success" if errors == 0 else "partial", "scan_run_id": run_id, "searches_completed": completed, "api_requests": api_requests, "offers_found": offers_found, "errors": errors}


def run_destination_scan(arrival_code: str, max_searches: int = 3) -> dict:
    arrival_code = str(arrival_code or "").upper().strip()
    allowed = {d["code"] for d in DESTINATIONS}
    if arrival_code not in allowed:
        return {"status": "error", "message": "Unsupported destination", "arrival_code": arrival_code}
    jobs = [j for j in _all_search_jobs() if j["arrival"] == arrival_code][:max(1, min(int(max_searches), 8))]
    run_id = create_scan_run(len(jobs))
    completed = offers_found = errors = api_requests = 0
    messages = []
    try:
        for job in jobs:
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
                    candidates=[]
                    if isinstance(analysis.get("below_typical_low_percent"), (int,float)):
                        candidates.append((analysis["below_typical_low_percent"],"serpapi_typical"))
                    if isinstance(history.get("median"), (int,float)) and history["median"] > 0:
                        candidates.append(((history["median"]-price)/history["median"]*100,"history"))
                    if isinstance(analysis.get("search_median"), (int,float)) and analysis["search_median"] > 0:
                        candidates.append(((analysis["search_median"]-price)/analysis["search_median"]*100,"search_distribution"))
                    if candidates:
                        discount, source=max(candidates,key=lambda x:x[0])
                        analysis["best_discount_percent"]=round(discount,1)
                        analysis["price_reference_source"]=source
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
        finish_scan_run(run_id,completed,offers_found,errors,"; ".join(messages)[:2000] or None)
    return {"status":"success" if errors==0 else "partial","scan_run_id":run_id,"destination":arrival_code,
            "searches_completed":completed,"api_requests":api_requests,"offers_found":offers_found,"errors":errors}
