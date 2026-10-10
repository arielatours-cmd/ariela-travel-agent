"""CJ (Commission Junction) commission sync - task 001a.

Detects an actual booking (not just an outbound click) by polling CJ's
Commission Detail API for commissions attributed to our sid=trip{id}
tracking parameter (see public_site._lodging_partner_url / _car_partner_url),
and turns a newly-seen, non-cancelled commission into
trip_requests.booked_confirmed_at + a queued "תיהנו בטיול" message.

IMPORTANT - verification gap, flagged in the QA report: this sandbox has no
outbound network access to developers.cj.com, so the exact GraphQL field
names below (publisherCommissions, forPublishers, sinceCommissionDate/
beforeCommissionDate, and the per-record field names) could NOT be checked
against CJ's live schema as the task spec required ("לוודא את שמות השדות
מול התיעוד העדכני של CJ לפני הכתיבה"). They reflect CJ's documented
Commission Detail API shape at the time this was written. Before setting
CJ_COMMISSIONS_SYNC_ENABLED=true in production: run one sync_cj_commissions()
call with real credentials (or an introspection query against
https://commissions.api.cj.com/query) and confirm the field names in
_RECORD_FIELDS actually match what CJ returns - a wrong field name fails the
whole GraphQL query (caught below and logged, never raised), not just that
field.
"""
import json
import logging
from datetime import datetime, timedelta, timezone

import requests

from config import CJ_API_TOKEN, CJ_PUBLISHER_ID, CJ_COMMISSIONS_SYNC_ENABLED
from database import (
    upsert_partner_commission, trip_has_valid_commission, connection, utc_now_iso,
)

log = logging.getLogger(__name__)

CJ_GRAPHQL_URL = "https://commissions.api.cj.com/query"

_QUERY = """
query PublisherCommissions($forPublishers: [ID!], $sinceDate: Date!, $beforeDate: Date!) {
  publisherCommissions(
    forPublishers: $forPublishers
    sincePostingDate: $sinceDate
    beforePostingDate: $beforeDate
  ) {
    count
    records {
      commissionId
      sid
      actionStatus
      advertiserName
      eventDate
      postingDate
      saleAmountPubCurrency
      pubCommissionAmountPubCurrency
      pubCurrency
    }
  }
}
"""

_CANCELLED_STATUSES = {"cancelled", "canceled", "corrected", "returned"}


def _extract_trip_id(sid: str):
    sid = str(sid or "").strip()
    if sid.startswith("trip") and sid[4:].isdigit():
        return int(sid[4:])
    return None


def sync_cj_commissions(days_back: int = 7) -> dict:
    """Pull CJ commissions posted in the last `days_back` days (max 31 per
    CJ's own request-range limit), upsert them, and queue a booking-congrats
    message for every trip whose FIRST valid (non-cancelled) commission just
    appeared. Never raises - a sync failure is logged and reported in the
    returned dict, never allowed to break the scheduler."""
    if not CJ_COMMISSIONS_SYNC_ENABLED or not CJ_API_TOKEN or not CJ_PUBLISHER_ID:
        return {"status": "disabled"}

    days_back = max(1, min(int(days_back), 31))
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days_back)).date().isoformat()
    before = now.date().isoformat()

    try:
        response = requests.post(
            CJ_GRAPHQL_URL,
            headers={
                "Authorization": f"Bearer {CJ_API_TOKEN}",
                "Content-Type": "application/json",
            },
            json={
                "query": _QUERY,
                "variables": {
                    "forPublishers": [CJ_PUBLISHER_ID],
                    "sinceDate": since,
                    "beforeDate": before,
                },
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        log.exception("CJ commission sync: network error")
        return {"status": "error", "message": str(exc)}

    try:
        data = response.json()
    except ValueError:
        log.error("CJ commission sync: non-JSON response (HTTP %s)", response.status_code)
        return {"status": "error", "message": f"HTTP {response.status_code}, non-JSON response"}

    if not response.ok or data.get("errors"):
        log.error("CJ commission sync failed: HTTP %s, errors=%s", response.status_code, data.get("errors"))
        return {"status": "error", "message": str(data.get("errors") or response.status_code)}

    records = (((data.get("data") or {}).get("publisherCommissions") or {}).get("records")) or []
    new_commissions = 0
    trips_confirmed = []
    trips_cancelled = []

    for record in records:
        try:
            commission_id = str(record.get("commissionId") or "").strip()
            if not commission_id:
                continue
            sid = record.get("sid")
            trip_id = _extract_trip_id(sid)
            action_status = str(record.get("actionStatus") or "")
            is_new = upsert_partner_commission(
                commission_id=commission_id, trip_id=trip_id,
                advertiser_name=record.get("advertiserName"), action_status=action_status,
                sale_amount=record.get("saleAmountPubCurrency"),
                commission_amount=record.get("pubCommissionAmountPubCurrency"),
                currency=record.get("pubCurrency"), event_date=record.get("eventDate"),
                posting_date=record.get("postingDate"), raw=record,
            )
            if is_new:
                new_commissions += 1
            if trip_id is None:
                continue

            cancelled = action_status.lower() in _CANCELLED_STATUSES
            amount = record.get("pubCommissionAmountPubCurrency")
            zeroed = amount is not None and float(amount) <= 0

            if not cancelled and not zeroed:
                if _mark_trip_booked(trip_id, "cj_commission"):
                    trips_confirmed.append(trip_id)
            elif (cancelled or zeroed) and not trip_has_valid_commission(trip_id, exclude_commission_id=commission_id):
                if _mark_trip_cancelled(trip_id):
                    trips_cancelled.append(trip_id)
        except Exception:
            log.exception("CJ commission sync: failed to process one record")

    return {
        "status": "ok", "fetched": len(records), "new_commissions": new_commissions,
        "trips_confirmed": trips_confirmed, "trips_cancelled": trips_cancelled,
    }


def _mark_trip_booked(trip_id: int, source: str) -> bool:
    """Returns True only the first time this trip is confirmed booked (so the
    caller can decide to queue the congrats message exactly once)."""
    with connection() as conn:
        row = conn.execute(
            "SELECT booked_confirmed_at FROM trip_requests WHERE id=?", (trip_id,)
        ).fetchone()
        if not row or row["booked_confirmed_at"]:
            return False
        conn.execute(
            "UPDATE trip_requests SET booked_confirmed_at=?, booked_source=? WHERE id=?",
            (utc_now_iso(), source, trip_id),
        )
        conn.commit()
    from trip_lifecycle_messages import queue_booking_congrats
    queue_booking_congrats(trip_id)
    return True


def _mark_trip_cancelled(trip_id: int) -> bool:
    with connection() as conn:
        row = conn.execute(
            "SELECT booking_cancelled_at FROM trip_requests WHERE id=?", (trip_id,)
        ).fetchone()
        if not row or row["booking_cancelled_at"]:
            return False
        conn.execute(
            "UPDATE trip_requests SET booking_cancelled_at=? WHERE id=?",
            (utc_now_iso(), trip_id),
        )
        conn.commit()
    return True
