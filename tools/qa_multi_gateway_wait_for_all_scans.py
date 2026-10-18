"""QA for a bug Carmit found live on the production site (2026-10-14): with
2 candidate destination gateways left open (e.g. both Larnaca and Paphos -
the customer never narrowed to one), she got navigated to her vacation page
with a single Larnaca result, went back to the chat, and later got
navigated again with an additional Paphos result that had never actually
been searched for her trip. Her own diagnosis: "in the case of 2 airports -
don't transfer to the vacation page until all the scans are finished."

Root cause confirmed by reading the code (not guessed), in two places:

1. ariella_start_flight_search's "DB-first" fast path (public_site.py):
   as soon as ANY qualifying offer already existed in the shared 48h
   inventory for ANY ONE of the candidate destination codes, it declared
   _flight_search_finished=True immediately and skipped queuing the real
   scan (_queue_customer_scan) ENTIRELY - so the other candidate gateway
   was never searched for this trip at all, only picked up later by an
   unrelated general background scan.

2. /trip/<id>/flight-status (trip_flight_status): "ready" fired as soon as
   ANY offers were resolvable from the shared inventory, regardless of
   whether they covered every candidate destination code - so even when
   the real scan DID get queued, a lucky partial match from the general
   inventory could still make the waiting page navigate away early.

Fixed both: the fast DB-first path only skips the real scan when it
already covers every candidate code; the status endpoint only reports
"ready" once the resolved offers cover every candidate code (or the real
search has genuinely finished).

Run: python3 tools/qa_multi_gateway_wait_for_all_scans.py
"""
import os
import sqlite3
import sys
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

import public_site
from werkzeug.security import generate_password_hash

DB = database.DB_PATH
client = public_site.site.app._get_current_object().test_client() if hasattr(public_site.site, "app") else None

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# ============================================================
# Part 1: the DB-first coverage condition itself (the exact logic added at
# the "if existing_matches:" branch in ariella_start_flight_search)
# ============================================================
def db_first_covers_all_codes(destination_codes, existing_matches):
    existing_covered_codes = {str(o.get("arrival_code") or "").upper() for o in existing_matches}
    return bool(destination_codes) and set(destination_codes) <= existing_covered_codes


check("partial coverage (only LCA matched out of LCA+PFO) -> does not count as full coverage",
      db_first_covers_all_codes(["LCA", "PFO"], [{"arrival_code": "LCA"}]) is False)
check("full coverage (both LCA and PFO matched) -> counts as full coverage",
      db_first_covers_all_codes(["LCA", "PFO"], [{"arrival_code": "LCA"}, {"arrival_code": "PFO"}]) is True)
check("single-candidate destination with a match -> still counts as full coverage (regression guard)",
      db_first_covers_all_codes(["LCA"], [{"arrival_code": "LCA"}]) is True)
check("no destination codes at all -> never falsely counts as covered",
      db_first_covers_all_codes([], [{"arrival_code": "LCA"}]) is False)
check("no matches at all -> never counts as covered",
      db_first_covers_all_codes(["LCA", "PFO"], []) is False)

# ============================================================
# Part 2: /trip/<id>/flight-status end to end, via the real Flask route,
# mocking only the inventory lookups (not the matching heuristics) so this
# is robust to unrelated changes in offer-qualification logic.
# ============================================================
import app as app_module
client = app_module.app.test_client()


def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA Multi-Gateway", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def _make_trip(member_id, destinations, flight_search_finished=False):
    import json
    answers = {
        "origin_airports": ["TLV"], "destinations": destinations,
        "date_mode": "exact", "departure_date": "2026-12-06", "return_date": "2026-12-11",
        "_requested_services": ["flights"],
        "_flight_search_finished": flight_search_finished,
    }
    with sqlite3.connect(DB) as conn:
        cur = conn.execute(
            "INSERT INTO trip_requests (member_id, request_name, created_at, status, answers_json) VALUES(?,?,?,?,?)",
            (member_id, "קפריסין", datetime.now(timezone.utc).isoformat(), "active", json.dumps(answers, ensure_ascii=False)),
        )
        return cur.lastrowid


member_id = _make_member("qa-multi-gateway@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id

# --- Scenario A: 2 candidate gateways (LCA, PFO), scan not yet finished,
#     but the shared inventory already resolves a match for ONLY LCA ->
#     status must stay "searching", not "ready" ---
trip_a = _make_trip(member_id, "LCA,PFO", flight_search_finished=False)
with patch.object(public_site, "recent_offers", return_value=[]), \
     patch.object(public_site, "_resolved_trip_offers", return_value=[{"arrival_code": "LCA", "offer_id": 1}]):
    r = client.get(f"/trip/{trip_a}/flight-status")
data_a = r.get_json()
check("2 candidate gateways, only one resolved, search not finished -> status stays 'searching'",
      data_a["status"] == "searching")
check("2 candidate gateways, only one resolved -> flight stage not marked complete",
      data_a["stages"]["flight"] == "searching")

# --- Scenario B: same 2 candidate gateways, both now resolve offers ->
#     status becomes "ready" ---
with patch.object(public_site, "recent_offers", return_value=[]), \
     patch.object(public_site, "_resolved_trip_offers", return_value=[{"arrival_code": "LCA", "offer_id": 1}, {"arrival_code": "PFO", "offer_id": 2}]):
    r2 = client.get(f"/trip/{trip_a}/flight-status")
data_b = r2.get_json()
check("2 candidate gateways, both resolved -> status becomes 'ready'", data_b["status"] == "ready")

# --- Scenario C: the real search genuinely finished (even with only
#     partial/no offers resolvable right now) -> still reported ready,
#     since the authoritative flag says the search is actually done ---
trip_c = _make_trip(member_id, "LCA,PFO", flight_search_finished=True)
with patch.object(public_site, "recent_offers", return_value=[]), \
     patch.object(public_site, "_resolved_trip_offers", return_value=[{"arrival_code": "LCA", "offer_id": 1}]):
    r3 = client.get(f"/trip/{trip_c}/flight-status")
data_c = r3.get_json()
check("search genuinely finished (flag true) -> status is 'ready' even with partial coverage",
      data_c["status"] == "ready")

# --- Scenario D: regression guard - a single-destination trip (no open
#     gateway choice) still works exactly as before ---
trip_d = _make_trip(member_id, "LCA", flight_search_finished=False)
with patch.object(public_site, "recent_offers", return_value=[]), \
     patch.object(public_site, "_resolved_trip_offers", return_value=[{"arrival_code": "LCA", "offer_id": 1}]):
    r4 = client.get(f"/trip/{trip_d}/flight-status")
data_d = r4.get_json()
check("single-destination trip with a resolved offer -> still 'ready' (unaffected by this fix)",
      data_d["status"] == "ready")

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM trip_requests WHERE member_id=?", (member_id,))
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL MULTI-GATEWAY WAIT-FOR-ALL-SCANS TESTS PASSED")
