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


def resolve_booking_target(offer: dict, force_refresh: bool = False) -> BookerTarget:
    """Open Ariella's recommended supplier and optionally revalidate a stale deal.

    For deals older than 48 hours, force_refresh=True deliberately skips the saved
    booking URL and asks the provider again using the exact round-trip booking token.
    If the provider no longer confirms an actionable booking path, Ariella fails
    closed instead of sending the customer to a stale offer.
    """
    recommended = str(offer.get("booking_supplier") or offer.get("airline") or "").strip()
    preferred = _norm(recommended)
    stored_url = offer.get("booking_request_url")
    stored_post = offer.get("booking_request_post_data")

    if stored_url and not force_refresh:
        return BookerTarget(
            url=stored_url,
            fields=parse_qsl(stored_post, keep_blank_values=True) if stored_post else [],
            supplier=recommended,
            mode="recommended_supplier",
            exact=True,
        )

    token = offer.get("booking_token") or (offer.get("flight") or {}).get("booking_token")
    if token and SERPAPI_API_KEY:
        try:
            response = requests.get(
                "https://serpapi.com/search.json",
                params={
                    "engine": "google_flights",
                    "booking_token": token,
                    "api_key": SERPAPI_API_KEY,
                    "hl": "en",
                    "gl": "il",
                    "currency": "ILS",
                },
                timeout=45,
            )
            data = response.json()
            for group in data.get("booking_options") or []:
                if group.get("separate_tickets"):
                    continue
                part = group.get("together") or {}
                if preferred and _norm(part.get("book_with")) != preferred:
                    continue
                req = part.get("booking_request") or {}
                if req.get("url"):
                    return BookerTarget(
                        url=req.get("url"),
                        fields=_request_fields(req),
                        supplier=part.get("book_with") or recommended,
                        mode="recommended_supplier_revalidated" if force_refresh else "recommended_supplier_refreshed",
                        exact=True,
                    )
        except Exception:
            pass

    if force_refresh:
        return BookerTarget(
            url=None,
            fields=[],
            supplier=recommended,
            mode="stale_deal_revalidation_failed",
            exact=False,
            note="הדיל נשמר לצפייה, אך לא ניתן היה לאמת מחדש את הזמינות אצל הספק.",
        )

    return BookerTarget(
        url=None,
        fields=[],
        supplier=recommended,
        mode="recommended_supplier_unavailable",
        exact=False,
        note="מסלול ההזמנה אצל הספק המומלץ אינו זמין כרגע.",
    )
