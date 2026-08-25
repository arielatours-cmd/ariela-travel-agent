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
    """Open Ariella's recommended supplier, not a marketplace of alternatives.

    BOOKER's responsibility ends when the customer reaches the recommended
    supplier with the correct route/dates and can choose the supplier's offered
    flight time/fare family. The customer then controls fare upgrades and payment.
    """
    recommended = str(offer.get("booking_supplier") or offer.get("airline") or "").strip()
    preferred = _norm(recommended)
    stored_url = offer.get("booking_request_url")
    stored_post = offer.get("booking_request_post_data")

    # The booking_request saved when Ariella selected the supplier is the primary
    # path. For airline sites (including EL AL), route/date handoff is acceptable:
    # the airline may offer a small set of same-day flight times and fare families.
    if stored_url:
        return BookerTarget(
            url=stored_url,
            fields=parse_qsl(stored_post, keep_blank_values=True) if stored_post else [],
            supplier=recommended,
            mode="recommended_supplier",
            exact=True,
        )

    # Refresh the exact round-trip token, but ONLY accept Ariella's recommended
    # supplier. Never replace it with a cheaper marketplace seller.
    token = offer.get("booking_token") or (offer.get("flight") or {}).get("booking_token")
    if token and SERPAPI_API_KEY:
        try:
            data = requests.get(
                "https://serpapi.com/search.json",
                params={"engine":"google_flights","booking_token":token,
                        "api_key":SERPAPI_API_KEY,"hl":"en","gl":"il","currency":"ILS"},
                timeout=45,
            ).json()
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
                        mode="recommended_supplier_refreshed",
                        exact=True,
                    )
        except Exception:
            pass

    # Do not expose competing booking suppliers. If the recommended supplier
    # handoff is unavailable, fail closed back to Ariella rather than showing a
    # marketplace that can confuse the customer.
    return BookerTarget(
        url=None, fields=[], supplier=recommended,
        mode="recommended_supplier_unavailable", exact=False,
        note="מסלול ההזמנה אצל הספק המומלץ אינו זמין כרגע.",
    )
