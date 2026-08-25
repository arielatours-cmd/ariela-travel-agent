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


# Supplier flows that live QA has shown are NOT safe to treat as an exact
# selected-flight handoff. They may preserve route/dates but still require the
# user to reselect outbound/return.
UNRELIABLE_DIRECT_SUPPLIERS = {
    "el al", "elal", "אל על",
}

# OTAs/suppliers for which SerpApi booking_request is generally an actionable
# purchase-flow handoff. We still keep a fallback to the stored flight results.
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

    # Never prefer a direct supplier already proven to strand the customer.
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


def resolve_booking_target(offer: dict) -> BookerTarget:
    """Resolve the most actionable target for this exact deal.

    Priority:
    1. exact stored actionable supplier handoff
    2. refreshed booking-token options, avoiding known broken direct flows
    3. Google Flights/result context fallback
    """
    preferred = _norm(offer.get("booking_supplier"))
    stored_url = offer.get("booking_request_url")
    stored_post = offer.get("booking_request_post_data")
    stored_supplier = _norm(offer.get("booking_supplier"))

    if stored_url and stored_supplier not in UNRELIABLE_DIRECT_SUPPLIERS:
        return BookerTarget(
            url=stored_url,
            fields=parse_qsl(stored_post, keep_blank_values=True) if stored_post else [],
            supplier=offer.get("booking_supplier") or offer.get("airline") or "",
            mode="stored_exact",
            exact=True,
        )

    token = offer.get("booking_token") or (offer.get("flight") or {}).get("booking_token")
    if token and SERPAPI_API_KEY:
        try:
            data = requests.get(
                "https://serpapi.com/search.json",
                params={
                    "engine": "google_flights",
                    "booking_token": token,
                    "api_key": SERPAPI_API_KEY,
                    "hl": "en", "gl": "il", "currency": "ILS",
                },
                timeout=45,
            ).json()
            rows = []
            for group in data.get("booking_options") or []:
                if group.get("separate_tickets"):
                    continue
                part = group.get("together") or {}
                req = part.get("booking_request") or {}
                if not req.get("url"):
                    continue
                rows.append((_priority(part, preferred), part, req))
            if rows:
                rows.sort(key=lambda x: x[0])
                _, part, req = rows[0]
                if not _is_unreliable_direct(part):
                    return BookerTarget(
                        url=req.get("url"),
                        fields=_request_fields(req),
                        supplier=part.get("book_with") or offer.get("booking_supplier") or "",
                        mode="refreshed_exact",
                        exact=True,
                    )
        except Exception:
            pass

    return BookerTarget(
        url=offer.get("booking_url"),
        fields=[],
        supplier="Google Flights",
        mode="results_fallback",
        exact=False,
        note="הספק הישיר לא מאפשר כרגע מעבר אמין לטיסות שנבחרו מראש.",
    )
