import itertools
import os
from datetime import date, datetime, timedelta, timezone
import requests

from config import (
    AIRPORT_NAMES, DEPARTURE_AIRPORTS, DEPARTURE_OFFSETS_DAYS, DESTINATIONS,
    MAX_SEARCHES_PER_SCAN, SERPAPI_API_KEY, TRIP_LENGTHS_DAYS,
)
from database import create_scan_run, finish_scan_run, get_setting, insert_offer, set_setting
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
    return {
        "price": item.get("price"), "airline": first.get("airline"), "flight_number": first.get("flight_number"),
        "departure_airport": dep.get("id"), "departure_airport_name": AIRPORT_NAMES.get(dep.get("id"), dep.get("id")),
        "departure_time": dep.get("time"), "arrival_airport": arr.get("id"),
        "arrival_airport_name": AIRPORT_NAMES.get(arr.get("id"), arr.get("id")), "arrival_time": arr.get("time"),
        "total_duration_minutes": total, "actual_flight_duration_minutes": actual, "stops": len(layovers),
        "is_direct": len(layovers) == 0, "connections": connections,
        "baggage": {
            "personal_item": {"included": True, "price_each_way": 0, "estimated": True},
            "carry_on_8kg": {"included": False, "price_each_way": None, "estimated": True},
            "checked_bag_23kg": {"included": False, "price_each_way": None, "estimated": True},
        },
    }


def _deal_analysis(data: dict) -> dict:
    insights = data.get("price_insights") or {}
    lowest = insights.get("lowest_price")
    typical = insights.get("typical_price_range") or []
    level = str(insights.get("price_level") or "").lower()
    low = typical[0] if len(typical) >= 2 else None
    high = typical[1] if len(typical) >= 2 else None
    discount = round((low - lowest) / low * 100, 1) if isinstance(lowest, (int, float)) and isinstance(low, (int, float)) and low > 0 else None
    return {
        "is_exceptional_deal": level == "low" or (discount is not None and discount >= 15),
        "price_level": level or None, "lowest_price": lowest,
        "typical_price_low": low, "typical_price_high": high,
        "below_typical_low_percent": discount,
    }


def search_flights(departure: str, arrival: str, outbound_date: str, return_date: str) -> dict:
    params = {
        "engine": "google_flights", "api_key": _api_key(), "departure_id": departure,
        "arrival_id": arrival, "outbound_date": outbound_date, "return_date": return_date,
        "type": "1", "hl": "en", "gl": "il", "currency": "ILS", "travel_class": "1",
        "adults": "1", "children": "0", "bags": "0", "sort_by": "2", "deep_search": "true",
    }
    response = requests.get(SERPAPI_URL, params=params, timeout=60)
    response.raise_for_status()
    data = response.json()
    if data.get("error"):
        raise RuntimeError(data["error"])
    flights = (data.get("best_flights") or []) + (data.get("other_flights") or [])
    flights = [f for f in flights if isinstance(f.get("price"), (int, float))]
    flights.sort(key=lambda f: f["price"])
    metadata = data.get("search_metadata") or {}
    return {
        "route": f"{departure}-{arrival}", "departure_code": departure, "arrival_code": arrival,
        "departure_airport_name": AIRPORT_NAMES.get(departure, departure),
        "arrival_airport_name": AIRPORT_NAMES.get(arrival, arrival),
        "outbound": _date_with_weekday(outbound_date), "return": _date_with_weekday(return_date),
        "deal_analysis": _deal_analysis(data), "flights": [_summarize_flight(f) for f in flights[:5]],
        "booking_url": metadata.get("google_flights_url"),
    }


def _all_search_jobs() -> list[dict]:
    today = date.today()
    jobs = []
    destinations_by_code = {d["code"]: d for d in DESTINATIONS}
    for departure, destination, offset, trip_length in itertools.product(DEPARTURE_AIRPORTS, DESTINATIONS, DEPARTURE_OFFSETS_DAYS, TRIP_LENGTHS_DAYS):
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
    completed = offers_found = errors = 0
    error_messages: list[str] = []

    for job in jobs:
        try:
            result = search_flights(job["departure"], job["arrival"], job["outbound"], job["return"])
            completed += 1
            for flight in result["flights"]:
                score = calculate_deal_score(result["deal_analysis"], flight)
                offer = {
                    "observed_at": datetime.now(timezone.utc).isoformat(), "route": result["route"],
                    "departure_code": job["departure"], "arrival_code": job["arrival"],
                    "departure_airport_name": result["departure_airport_name"],
                    "arrival_airport_name": result["arrival_airport_name"],
                    "destination_name": job["destination_name"], "country_flag": job["country_flag"],
                    "outbound_date": job["outbound"], "return_date": job["return"],
                    "outbound": result["outbound"], "return": result["return"],
                    "deal_analysis": result["deal_analysis"], "flight": flight,
                    "deal_score": score, "booking_url": result["booking_url"],
                }
                insert_offer(run_id, offer)
                offers_found += 1
        except Exception as exc:
            errors += 1
            error_messages.append(f"{job['departure']}-{job['arrival']}: {exc}")

    finish_scan_run(run_id, completed, offers_found, errors, "; ".join(error_messages)[:2000] or None)
    return {
        "status": "success" if errors == 0 else "partial", "scan_run_id": run_id,
        "searches_planned": len(jobs), "searches_completed": completed,
        "offers_found": offers_found, "errors": errors, "error_messages": error_messages,
    }
