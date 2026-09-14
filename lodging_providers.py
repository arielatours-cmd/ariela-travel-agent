import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LodgingProviderStatus:
    provider: str
    enabled: bool
    configured: bool
    live_inventory: bool
    note: str


def provider_statuses():
    booking_key = os.getenv("BOOKING_DEMAND_API_KEY", "").strip()
    booking_affiliate = os.getenv("BOOKING_AFFILIATE_ID", "").strip()
    airbnb_enabled = os.getenv("AIRBNB_PARTNER_ENABLED", "false").strip().lower() == "true"
    airbnb_endpoint = os.getenv("AIRBNB_PARTNER_SEARCH_URL", "").strip()
    airbnb_token = os.getenv("AIRBNB_PARTNER_TOKEN", "").strip()

    booking_configured = bool(booking_key and booking_affiliate)
    airbnb_configured = bool(airbnb_enabled and airbnb_endpoint and airbnb_token)

    return [
        LodgingProviderStatus(
            provider="booking",
            enabled=True,
            configured=booking_configured,
            live_inventory=booking_configured,
            note=(
                "Booking.com provider configured"
                if booking_configured
                else "Missing BOOKING_DEMAND_API_KEY and/or BOOKING_AFFILIATE_ID"
            ),
        ),
        LodgingProviderStatus(
            provider="airbnb",
            enabled=airbnb_enabled,
            configured=airbnb_configured,
            live_inventory=airbnb_configured,
            note=(
                "Airbnb partner connection configured"
                if airbnb_configured
                else "Airbnb partner access/endpoint/token not configured"
            ),
        ),
    ]


def lodging_inventory_status():
    rows = provider_statuses()
    return {
        "providers": [
            {
                "provider": r.provider,
                "enabled": r.enabled,
                "configured": r.configured,
                "live_inventory": r.live_inventory,
                "note": r.note,
            }
            for r in rows
        ],
        "live_provider_count": sum(1 for r in rows if r.live_inventory),
        "live_inventory_available": any(r.live_inventory for r in rows),
    }
