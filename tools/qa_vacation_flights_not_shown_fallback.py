"""QA for the business owner's directive (20.10.2026, relayed by Shlomo,
vacation 259/trip #158): the owner confirmed the scan genuinely found real,
different-priced flights (TLV->LIS, 2027-03-21 to 2027-03-25, 7 rows visible
in /admin/scans) - but the customer's own vacation card in /account showed
none of them. Root cause, confirmed by reading the code (no production DB
access, so this is a code-level investigation, not a live repro):

/account resolves a FINISHED vacation's flights ONLY from its frozen
answers["_matched_offer_ids"] (public_site._resolved_trip_offers) - it never
looks at the shared offer pool again once the search is marked finished.
_customer_scan_worker's "initial" mode already had THREE fallback tiers
before this fix (exact match -> flexible dates -> over budget), each of
which EXCLUDES an offer outright on any single missed objective condition
(exact dates, direct-flight preference, trip length, a time-of-day
preference, etc.). When every one of several real, found offers each misses
a DIFFERENT one of these conditions, NONE of them survives any single tier,
_matched_offer_ids stays empty, and the vacation is frozen on nothing
forever - exactly the reported symptom.

Three fixes, all per the business owner's explicit instructions:

1. A fourth, final fallback tier (_closest_offers_regardless_of_conditions)
   that drops every objective-condition filter and shows the closest
   (cheapest) same-destination, complete-roundtrip offers that still exist,
   each labeled with exactly which condition it misses (reusing
   _objective_match_details' own human-readable reasons) - "never freeze on
   an empty list."
2. The scan worker's matching/pinning logic is now wrapped in its own
   try/except with a new ai_usage diagnostic event
   (customer_scan_worker_error) - "a scan must never fail silently."
3. A new admin recovery action, rematch_trip_without_new_scan (exposed as
   POST /admin/rematch-trip), re-runs the same four-tier chain against
   CURRENT inventory for an already-finished vacation stuck on an empty
   list - with NO new paid scan - for vacations (like 259) frozen before
   this fallback chain existed.

Run: python3 tools/qa_vacation_flights_not_shown_fallback.py
"""
import sys
import os
import sqlite3
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()
import public_site
import ai_usage

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


TEST_MEMBER_ID = 999201


def make_member():
    with sqlite3.connect(database.DB_PATH) as conn:
        conn.execute("DELETE FROM members WHERE id=?", (TEST_MEMBER_ID,))
        conn.execute(
            "INSERT INTO members (id, full_name,email,phone,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,datetime('now'),'active',0,'[]')",
            (TEST_MEMBER_ID, "QA Vacation 259", "qa-vacation259@example.com", "0500000000", "x"),
        )
        conn.commit()


def make_trip(trip_id, answers, status="active"):
    with sqlite3.connect(database.DB_PATH) as conn:
        conn.execute("DELETE FROM trip_requests WHERE id=?", (trip_id,))
        conn.execute(
            "INSERT INTO trip_requests (id, member_id, request_name, travel_window, status, answers_json, created_at) "
            "VALUES(?,?,?,?,?,?,datetime('now'))",
            (trip_id, TEST_MEMBER_ID, "ליסבון", "2027-03-21 - 2027-03-25", status, json.dumps(answers, ensure_ascii=False)),
        )
        conn.commit()


def make_offer(price_ils, outbound, ret, stops=0, arrival_code="LIS"):
    payload = {
        "destination_name": "ליסבון",
        "flight": {
            "departure_time": "08:00", "arrival_time": "12:00",
            "return_departure_time": "14:00", "return_arrival_time": "18:00",
            "stops": stops,
            "baggage": {"carry_on_8kg": {"included": True}, "checked_bag_23kg": {"included": True}},
        },
    }
    observed_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(database.DB_PATH) as conn:
        cur = conn.execute(
            "INSERT INTO scan_runs (started_at, status, searches_planned) VALUES (datetime('now'), 'done', 1)"
        )
        scan_run_id = cur.lastrowid
        cur = conn.execute(
            """INSERT INTO offers (scan_run_id, observed_at, route, departure_code, arrival_code, outbound_date,
               return_date, price_ils, score, score_label, departure_time, arrival_time, payload_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (scan_run_id, observed_at, f"TLV-{arrival_code}", "TLV", arrival_code, outbound, ret,
             price_ils, 70, "good", "08:00", "12:00", json.dumps(payload, ensure_ascii=False)),
        )
        conn.commit()
        return int(cur.lastrowid)


def cleanup():
    with sqlite3.connect(database.DB_PATH) as conn:
        conn.execute("DELETE FROM trip_requests WHERE member_id=?", (TEST_MEMBER_ID,))
        conn.execute("DELETE FROM members WHERE id=?", (TEST_MEMBER_ID,))
        conn.commit()


make_member()

# The real vacation 259/#158 shape: exact dates requested, a direct-flight
# preference set, no budget limit - and every found offer is non-direct and
# in a different month, so it misses BOTH the exact-dates tier and the
# flexible/same-month tier; no budget means the over-budget tier never
# applies either. Only the new 4th tier should ever show these.
TRIP_259_ANSWERS = {
    "destinations": "LIS", "origin_airports": ["TLV"],
    "date_mode": "exact", "departure_date": "2027-03-21", "return_date": "2027-03-25",
    "date_flex_days": 0, "duration_days": 5,
    "deal_priorities": ["direct"],
    "vacation_type": "standard",
}

# =====================================================================
# 1. _closest_offers_regardless_of_conditions - the new 4th tier itself.
# =====================================================================
make_trip(158001, TRIP_259_ANSWERS)
with sqlite3.connect(database.DB_PATH) as conn:
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM trip_requests WHERE id=?", (158001,)).fetchone()
trip_259 = public_site._trip_dict(row)

offer_cheap = make_offer(1800, "2027-04-10", "2027-04-14", stops=1)
offer_expensive = make_offer(2500, "2027-04-20", "2027-04-24", stops=1)
refreshed = database.recent_offers(limit=2000, minimum_score=None)
refreshed = [public_site._localize_offer_airports(o) for o in refreshed if o.get("id") in (offer_cheap, offer_expensive)]

check("tier 1 (exact match) correctly excludes both offers - wrong month "
      "AND non-direct, confirming this repro genuinely needs the new tier",
      public_site._customer_deal_choices(refreshed, trip_259, limit=5) == [])
check("tier 2 (flexible dates) also excludes both - different month, no "
      "second-chance flex requested",
      public_site._customer_alternative_choices(refreshed, trip_259, limit=5) == [])
check("tier 3 (over budget) is empty too - no budget_mode was ever set, so "
      "there is no 'over budget' concept to fall back on",
      public_site._over_budget_alternatives(refreshed, trip_259, limit=5) == [])

closest = public_site._closest_offers_regardless_of_conditions(refreshed, trip_259, limit=5)
check("the new 4th tier finally returns the real offers the scan found",
      len(closest) == 2)
check("cheapest offer sorts first",
      bool(closest) and closest[0].get("price_ils") == 1800)
check("each offer is labeled with the real reason it was shown despite "
      "missing a condition - here, the direct-flight preference",
      bool(closest) and "טיסה ישירה" in (closest[0].get("request_missed_reasons") or []))
check("the label itself is honest, not a bare match claim",
      bool(closest) and closest[0].get("customer_choice_label_he") == "הטיסה הקרובה ביותר שנמצאה")

# =====================================================================
# 2. _match_and_pin_initial_offers wires tier 4 into the real pin path.
# =====================================================================
answers_258 = dict(TRIP_259_ANSWERS)
pinned = public_site._match_and_pin_initial_offers(158001, trip_259, answers_258, refreshed)
check("_match_and_pin_initial_offers falls through all the way to tier 4 "
      "and reports something was pinned",
      pinned is True)
check("the closest-match flags are set so the UI can show the honest "
      "'not an exact match' framing",
      answers_258.get("_initial_exact_match_missing") is True
      and answers_258.get("_showing_closest_matches") is True)
with sqlite3.connect(database.DB_PATH) as conn:
    conn.row_factory = sqlite3.Row
    saved = json.loads(conn.execute("SELECT answers_json FROM trip_requests WHERE id=?", (158001,)).fetchone()["answers_json"])
check("the pinned ids are actually persisted to the trip row",
      bool(saved.get("_matched_offer_ids")))

# =====================================================================
# 3. The worker itself never fails silently - an exception in the
#    matching logic is caught, logged as a diagnostic event, and the
#    search still finishes so the waiting page never hangs forever.
# =====================================================================
make_trip(158002, dict(TRIP_259_ANSWERS, _flight_search_finished=False))
with patch.object(public_site, "_customer_deal_choices", side_effect=RuntimeError("qa-forced-matching-failure")):
    with patch.object(public_site, "run_customer_trip_search", return_value={"status": "success", "offers_found": 2, "api_requests": 1}):
        public_site._customer_scan_worker(158002, {}, mode="initial")
with sqlite3.connect(database.DB_PATH) as conn:
    conn.row_factory = sqlite3.Row
    row2 = conn.execute("SELECT answers_json FROM trip_requests WHERE id=?", (158002,)).fetchone()
answers2 = json.loads(row2["answers_json"])
check("a forced exception in the matching logic never crashes the worker "
      "or leaves the search un-finished - the waiting page still resolves",
      answers2.get("_flight_search_finished") is True)
diag_rows = ai_usage.diagnostic_rows("customer_scan_worker_error", include_test=True)
check("the failure is recorded as a diagnostic event, never silent",
      any(json.loads(r["details"] or "{}").get("trip_id") == 158002 for r in diag_rows))
check("the diagnostic event never contains the customer's own answers, "
      "only structured trip_id/mode/exception fields",
      all("destinations" not in (r.get("details") or "") for r in diag_rows
          if json.loads(r["details"] or "{}").get("trip_id") == 158002))

# =====================================================================
# 4. rematch_trip_without_new_scan - the admin recovery action for an
#    already-stuck vacation (like the real 259/#158).
# =====================================================================
check("rematch: a trip that doesn't exist at all is a clean error, never a crash",
      public_site.rematch_trip_without_new_scan(9999999).get("status") == "error")

make_trip(158003, TRIP_259_ANSWERS)  # _flight_search_finished never set
result_not_finished = public_site.rematch_trip_without_new_scan(158003)
check("rematch: a trip whose search hasn't finished yet is refused - this "
      "is a recovery action for a STUCK vacation, never a mid-search one",
      result_not_finished.get("status") == "error")

make_trip(158004, dict(TRIP_259_ANSWERS, _flight_search_finished=True, _matched_offer_ids=[offer_cheap]))
result_has_matches = public_site.rematch_trip_without_new_scan(158004)
check("rematch: a trip that already has real matched offers is left alone "
      "- never overwritten by a recovery action",
      result_has_matches.get("status") == "error")

# The real stuck-vacation shape: search finished, nothing ever got pinned.
make_trip(158005, dict(TRIP_259_ANSWERS, _flight_search_finished=True))
result_stuck = public_site.rematch_trip_without_new_scan(158005)
check("rematch: a genuinely stuck vacation (search finished, nothing "
      "pinned) is successfully re-matched against current inventory, with "
      "no new scan call",
      result_stuck.get("status") == "success" and result_stuck.get("pinned") is True)
with sqlite3.connect(database.DB_PATH) as conn:
    conn.row_factory = sqlite3.Row
    row5 = conn.execute("SELECT answers_json FROM trip_requests WHERE id=?", (158005,)).fetchone()
answers5 = json.loads(row5["answers_json"])
check("rematch: the real flights are now pinned where the customer's "
      "/account card will actually render them from",
      bool(answers5.get("_matched_offer_ids")))

cleanup()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL VACATION-FLIGHTS-NOT-SHOWN-FALLBACK TESTS PASSED")
