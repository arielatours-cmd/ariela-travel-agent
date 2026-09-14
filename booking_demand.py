import os
from typing import Any

import requests

BOOKING_DEMAND_API_KEY = os.getenv("BOOKING_DEMAND_API_KEY", "").strip()
BOOKING_AFFILIATE_ID = os.getenv("BOOKING_AFFILIATE_ID", "").strip()
BOOKING_DEMAND_BASE_URL = os.getenv("BOOKING_DEMAND_BASE_URL", "https://demandapi.booking.com/3.2").rstrip("/")


def is_configured() -> bool:
    return bool(BOOKING_DEMAND_API_KEY and BOOKING_AFFILIATE_ID)


def _headers() -> dict[str, str]:
    if not is_configured():
        raise RuntimeError("Booking.com Demand API credentials are not configured")
    return {
        "Authorization": f"Bearer {BOOKING_DEMAND_API_KEY}",
        "X-Affiliate-Id": BOOKING_AFFILIATE_ID,
        "Content-Type": "application/json",
    }


def _post(path: str, payload: dict[str, Any], timeout: int = 35) -> dict[str, Any]:
    response = requests.post(
        f"{BOOKING_DEMAND_BASE_URL}/{path.lstrip('/')}",
        headers=_headers(),
        json=payload,
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Booking Demand API error {response.status_code}: {response.text[:1200]}")
    return response.json()


def search_accommodations(
    *, city_id: int, checkin: str, checkout: str, adults: int,
    rooms: int = 1, children_ages: list[int] | None = None,
    filters: dict[str, Any] | None = None, currency: str = "ILS",
    platform: str = "mobile", booker_country: str = "il",
    maximum_results: int = 20,
) -> dict[str, Any]:
    """Search real accommodation inventory through Booking.com Demand API v3.2.

    The caller must first resolve the Booking city id using the common location endpoints.
    """
    guests: dict[str, Any] = {
        "number_of_adults": max(1, int(adults or 1)),
        "number_of_rooms": max(1, int(rooms or 1)),
    }
    if children_ages:
        guests["children"] = [max(0, int(age)) for age in children_ages]
    payload: dict[str, Any] = {
        "booker": {"country": str(booker_country).lower(), "platform": platform},
        "checkin": checkin,
        "checkout": checkout,
        "city": int(city_id),
        "currency": currency,
        "guests": guests,
        "extras": ["products"],
        "rows": max(10, min(100, int(maximum_results or 20))),
    }
    if filters:
        payload["filters"] = filters
    return _post("accommodations/search", payload)


def search_cars(
    *, pickup_airport: str, dropoff_airport: str,
    pickup_datetime: str, dropoff_datetime: str, driver_age: int,
    filters: dict[str, Any] | None = None, currency: str = "ILS",
    booker_country: str = "il", maximum_results: int = 20,
) -> dict[str, Any]:
    """Search real rental-car inventory through Booking.com Demand API v3.2."""
    payload: dict[str, Any] = {
        "booker": {"country": str(booker_country).lower()},
        "currency": currency,
        "driver": {"age": max(18, min(99, int(driver_age)))},
        "route": {
            "pickup": {"datetime": pickup_datetime, "location": {"airport": pickup_airport.upper()}},
            "dropoff": {"datetime": dropoff_datetime, "location": {"airport": dropoff_airport.upper()}},
        },
        "maximum_results": max(10, min(100, int(maximum_results or 20))),
    }
    if filters:
        payload["filters"] = filters
    return _post("cars/search", payload)
