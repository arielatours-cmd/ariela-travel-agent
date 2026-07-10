import os
from datetime import date, timedelta
import requests

SERPAPI_URL = "https://serpapi.com/search.json"

DESTINATIONS = [
    {"code": "ATH", "name": "Athens"},
    {"code": "LCA", "name": "Larnaca"},
    {"code": "BUD", "name": "Budapest"},
    {"code": "VIE", "name": "Vienna"},
    {"code": "SOF", "name": "Sofia"}
]

def _api_key():
    key = os.getenv("SERPAPI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("SERPAPI_API_KEY is missing in Render Environment.")
    return key

def _summarize_flight(item):
    segments = item.get("flights") or []
    segment = segments[0] if segments else {}
    departure = segment.get("departure_airport") or {}
    arrival = segment.get("arrival_airport") or {}
    return {
        "price": item.get("price"),
        "airline": segment.get("airline"),
        "flight_number": segment.get("flight_number"),
        "departure_airport": departure.get("id"),
        "departure_time": departure.get("time"),
        "arrival_airport": arrival.get("id"),
        "arrival_time": arrival.get("time"),
        "duration_minutes": item.get("total_duration"),
        "stops": len(item.get("layovers") or []),
        "type": item.get("type")
    }

def _deal_analysis(data):
    insights = data.get("price_insights") or {}
    lowest = insights.get("lowest_price")
    typical = insights.get("typical_price_range") or []
    price_level = str(insights.get("price_level") or "").lower()

    typical_low = typical[0] if len(typical) >= 2 else None
    typical_high = typical[1] if len(typical) >= 2 else None
    discount_percent = None

    if isinstance(lowest, (int, float)) and isinstance(typical_low, (int, float)) and typical_low > 0:
        discount_percent = round((typical_low - lowest) / typical_low * 100, 1)

    is_exceptional = price_level == "low" or (
        discount_percent is not None and discount_percent >= 15
    )

    return {
        "is_exceptional_deal": is_exceptional,
        "price_level": price_level or None,
        "lowest_price": lowest,
        "typical_price_low": typical_low,
        "typical_price_high": typical_high,
        "below_typical_low_percent": discount_percent
    }

def search_flights(departure, arrival, outbound_date, return_date=None,
                   adults="1", children="0", carry_on_bags="0"):
    params = {
        "engine": "google_flights",
        "api_key": _api_key(),
        "departure_id": departure,
        "arrival_id": arrival,
        "outbound_date": outbound_date,
        "hl": "en",
        "gl": "il",
        "currency": "ILS",
        "travel_class": "1",
        "adults": adults,
        "children": children,
        "bags": carry_on_bags,
        "sort_by": "2",
        "deep_search": "true"
    }

    if return_date:
        params["type"] = "1"
        params["return_date"] = return_date
    else:
        params["type"] = "2"

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
        "status": "success",
        "route": f"{departure}-{arrival}",
        "outbound_date": outbound_date,
        "return_date": return_date,
        "deal_analysis": _deal_analysis(data),
        "cheapest_flights": [_summarize_flight(f) for f in flights[:5]],
        "google_flights_url": metadata.get("google_flights_url"),
        "baggage_note": "The bags parameter covers carry-on bags, not checked baggage."
    }

def scan_configured_routes():
    today = date.today()
    outbound = today + timedelta(days=45)
    return_date = outbound + timedelta(days=5)

    results = []
    exceptional = []

    for destination in DESTINATIONS:
        try:
            result = search_flights(
                departure="TLV",
                arrival=destination["code"],
                outbound_date=outbound.isoformat(),
                return_date=return_date.isoformat(),
                carry_on_bags="1"
            )
            result["destination_name"] = destination["name"]
            results.append(result)
            if result["deal_analysis"]["is_exceptional_deal"]:
                exceptional.append(result)
        except Exception as exc:
            results.append({
                "status": "error",
                "destination": destination,
                "message": str(exc)
            })

    return {
        "status": "success",
        "scan_dates": {
            "outbound": outbound.isoformat(),
            "return": return_date.isoformat()
        },
        "searches_used": len(DESTINATIONS),
        "exceptional_deals_found": len(exceptional),
        "exceptional_deals": exceptional,
        "all_results": results
    }
