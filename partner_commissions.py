"""CJ (Commission Junction) commission sync - task 001a.

Detects an actual booking (not just an outbound click) by polling CJ's
Commission Detail API for commissions attributed to our sid=trip{id}
tracking parameter (see public_site._lodging_partner_url / _car_partner_url),
and turns a newly-seen, non-cancelled commission into
trip_requests.booked_confirmed_at + a queued "תיהנו בטיול" message.

IMPORTANT - verification gap, flagged in the QA report: this sandbox has no
outbound network access to developers.cj.com, so the exact GraphQL field
names below (publisherCommissions, forPublishers, sinceCommissionDate/
beforeCommissionDate, and the per-record field names in _RECORD_FIELDS)
could NOT be checked against CJ's live schema as the task spec required
("לוודא את שמות השדות מול התיעוד העדכני של CJ לפני הכתיבה"). They reflect
CJ's documented Commission Detail API shape at the time this was written.

Task 001b (see GET /admin/cj-check in app.py / cj_connection_check below)
is exactly this missing verification step, made runnable with real
credentials from outside this sandbox: it sends the same query read-only
(no DB writes, no queued messages, independent of
CJ_COMMISSIONS_SYNC_ENABLED) and reports which _RECORD_FIELDS actually came
back, falling back to live schema introspection if a field name is wrong.
Before setting CJ_COMMISSIONS_SYNC_ENABLED=true in production, open that
endpoint once and confirm it reports ok:true.
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

# Generated from _RECORD_FIELDS (not hand-duplicated) so the query body and
# the field_check/introspection logic in cj_connection_check below can never
# drift out of sync with each other.
_RECORD_FIELDS = (
    "commissionId", "sid", "actionStatus", "advertiserName", "eventDate",
    "postingDate", "saleAmountPubCurrency", "pubCommissionAmountPubCurrency",
    "pubCurrency",
)

_QUERY = """
query PublisherCommissions($forPublishers: [ID!], $sinceDate: Date!, $beforeDate: Date!) {
  publisherCommissions(
    forPublishers: $forPublishers
    sincePostingDate: $sinceDate
    beforePostingDate: $beforeDate
  ) {
    count
    records {
      %s
    }
  }
}
""" % "\n      ".join(_RECORD_FIELDS)

_CANCELLED_STATUSES = {"cancelled", "canceled", "corrected", "returned"}


def _fetch_cj_records(since: str, before: str) -> dict:
    """One POST to CJ's Commission Detail GraphQL endpoint - returns the raw
    outcome, never raises. Shared by sync_cj_commissions (which also
    persists/side-effects on the result) and cj_connection_check (task 001b,
    strictly read-only), so both send the exact same request shape. Never
    includes CJ_API_TOKEN in the returned dict."""
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
        return {"ok": False, "http_status": None, "graphql_errors": [str(exc)], "records": []}

    try:
        data = response.json()
    except ValueError:
        return {
            "ok": False, "http_status": response.status_code,
            "graphql_errors": [f"non-JSON response (HTTP {response.status_code})"], "records": [],
        }

    errors = data.get("errors") or []
    records = (((data.get("data") or {}).get("publisherCommissions") or {}).get("records")) or []
    return {
        "ok": bool(response.ok and not errors),
        "http_status": response.status_code,
        "graphql_errors": errors,
        "records": records,
    }


def _unwrap_type_name(type_ref):
    """GraphQL wraps a field's type in NON_NULL/LIST layers (e.g.
    [PublisherCommissionRecord!]!) - walk down to the actual named type."""
    node = type_ref or {}
    while node and not node.get("name"):
        node = node.get("ofType") or {}
    return node.get("name")


def _introspect_query_field_type(field_name: str):
    """Unwrapped return type name of one field on the schema's root query
    type - found via __schema.queryType (never a hardcoded "Query" name,
    since a schema can call its root type anything). Returns None on any
    failure (network, auth, missing field, etc) - this is a best-effort
    diagnostic helper, never load-bearing for the real sync."""
    query = """
    query IntrospectQueryField {
      __schema {
        queryType {
          fields {
            name
            type { kind name ofType { kind name ofType { kind name ofType { kind name } } } }
          }
        }
      }
    }
    """
    try:
        response = requests.post(
            CJ_GRAPHQL_URL,
            headers={"Authorization": f"Bearer {CJ_API_TOKEN}", "Content-Type": "application/json"},
            json={"query": query}, timeout=30,
        )
        data = response.json()
    except Exception:
        return None
    fields = (((data.get("data") or {}).get("__schema") or {}).get("queryType") or {}).get("fields") or []
    for f in fields:
        if f.get("name") == field_name:
            return _unwrap_type_name(f.get("type"))
    return None


def _introspect_type_field_type(type_name: str, field_name: str):
    """Unwrapped type name of one field on a named (non-root) type - e.g.
    the type of PublisherCommissions.records. Returns None on any failure."""
    query = """
    query IntrospectTypeField($name: String!) {
      __type(name: $name) {
        fields {
          name
          type { kind name ofType { kind name ofType { kind name ofType { kind name } } } }
        }
      }
    }
    """
    try:
        response = requests.post(
            CJ_GRAPHQL_URL,
            headers={"Authorization": f"Bearer {CJ_API_TOKEN}", "Content-Type": "application/json"},
            json={"query": query, "variables": {"name": type_name}}, timeout=30,
        )
        data = response.json()
    except Exception:
        return None
    type_info = ((data.get("data") or {}).get("__type")) or {}
    for f in (type_info.get("fields") or []):
        if f.get("name") == field_name:
            return _unwrap_type_name(f.get("type"))
    return None


def _introspect_type_fields(type_name: str) -> list:
    """Field names of a named type. Returns [] on any failure."""
    query = """
    query IntrospectTypeFields($name: String!) {
      __type(name: $name) { fields { name } }
    }
    """
    try:
        response = requests.post(
            CJ_GRAPHQL_URL,
            headers={"Authorization": f"Bearer {CJ_API_TOKEN}", "Content-Type": "application/json"},
            json={"query": query, "variables": {"name": type_name}}, timeout=30,
        )
        data = response.json()
    except Exception:
        return []
    type_info = ((data.get("data") or {}).get("__type")) or {}
    return [f.get("name") for f in (type_info.get("fields") or []) if f.get("name")]


def cj_introspect_record_fields() -> list:
    """Best-effort discovery of the real field names CJ's live schema
    exposes for one commission record - by walking the schema from the root
    query field (publisherCommissions) down to its records field's element
    type, rather than guessing/hardcoding a record type name that might not
    match CJ's actual schema (exactly the kind of mismatch task 001b exists
    to catch - e.g. the task spec's own "shopperId" vs this file's "sid").
    Returns [] if any step fails - diagnostic aid only, never load-bearing."""
    if not CJ_API_TOKEN:
        return []
    payload_type = _introspect_query_field_type("publisherCommissions")
    if not payload_type:
        return []
    record_type = _introspect_type_field_type(payload_type, "records")
    if not record_type:
        return []
    return _introspect_type_fields(record_type)


_FIELD_ERROR_HINTS = ("field", "cannot query", "unknown argument", "did not exist", "doesn't exist", "not defined")


def cj_connection_check(days_back: int = 31) -> dict:
    """Read-only diagnostic for task 001b: confirm CJ_API_TOKEN/
    CJ_PUBLISHER_ID actually work against CJ's live schema and that _QUERY's
    field names match it - WITHOUT writing to partner_commissions or queuing
    any message, and regardless of CJ_COMMISSIONS_SYNC_ENABLED (that switch
    only gates the real recurring sync in sync_cj_commissions above; this
    check must work to decide whether it's even safe to turn that on).
    Never returns or logs CJ_API_TOKEN."""
    if not CJ_API_TOKEN or not CJ_PUBLISHER_ID:
        return {"ok": False, "message": "CJ_API_TOKEN or CJ_PUBLISHER_ID is not configured"}

    days_back = max(1, min(int(days_back), 31))
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days_back)).date().isoformat()
    before = now.date().isoformat()

    fetched = _fetch_cj_records(since, before)
    records = fetched["records"]
    first_record = records[0] if records else None
    result = {
        "ok": fetched["ok"],
        "http_status": fetched["http_status"],
        "graphql_errors": fetched["graphql_errors"],
        "records_count": len(records),
        "sample": [
            {k: record.get(k) for k in ("commissionId", "sid", "actionStatus", "advertiserName", "postingDate")}
            for record in records[:3]
        ],
        "field_check": (
            {field: (field in first_record) for field in _RECORD_FIELDS}
            if first_record is not None else
            {field: None for field in _RECORD_FIELDS}
        ),
    }

    errors_text = " ".join(
        str(e.get("message") if isinstance(e, dict) else e) for e in fetched["graphql_errors"]
    ).lower()
    if fetched["graphql_errors"] and any(hint in errors_text for hint in _FIELD_ERROR_HINTS):
        result["hint"] = "שם שדה שגוי. לתקן את _QUERY לפי השגיאה."
        result["available_fields"] = cj_introspect_record_fields()

    return result


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

    fetched = _fetch_cj_records(since, before)
    if not fetched["ok"]:
        log.error("CJ commission sync failed: HTTP %s, errors=%s", fetched["http_status"], fetched["graphql_errors"])
        return {"status": "error", "message": str(fetched["graphql_errors"] or fetched["http_status"])}

    records = fetched["records"]
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
