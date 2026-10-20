"""QA for Shlomo's follow-up review (20.10.2026, after #92 merged - vacation
259/trip #158, second priority per his explicit order: pushed BEFORE the
Bologna/Bari/Seville-Granada/Zurich batch so the business owner can click it
herself once Shaked reviews).

Two problems found in the #92 fix, both fixed here:

1. No button. The business owner works from her phone and can't send a
   manual POST to /admin/rematch-trip. Added a "הצג טיסות מחדש" button on
   the vacation's own row in /admin/scans, shown once that scan has
   finished (s.finished_at) and carrying a trip_id. It posts with the
   existing route's own admin-session protection - no token in the URL at
   all (the form relies purely on the already-authenticated admin session
   cookie, never a query-string token that could leak into logs/referrers).

2. The 48-hour window. rematch_trip_without_new_scan used
   _recent_inventory_48h() - a blanket window across ALL customers' recent
   offers. Her exact objection: vacation 259's own offers were scanned
   19.10 05:30 UTC, so THAT window already closes 21.10 05:30 UTC - once it
   passes, a blanket recent-inventory call can no longer find this trip's
   own offers at all (or, in the other direction, could surface unrelated
   customers' offers that merely happen to still be within the blanket
   window). Fixed: rematch is now scoped to the offers THIS vacation's own
   scan_run actually found (scan_runs.trip_id -> scan_run_offers), via the
   new _inventory_for_trip_scan_run - reusing recent_offers(offer_ids=...)
   for the full, correctly-populated row shape (not the thinner
   offers_for_scan_run projection, which is missing fields like stops/
   departure_time/baggage every matching tier actually needs). Also drops
   any offer whose own flight date has already passed, per her explicit
   instruction ("הצעה שתאריך הטיסה שלה עבר לא מוצגת").

Run: python3 tools/qa_vacation_rematch_scan_run_scoped.py
"""
import os
import sys
import sqlite3
import json
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()
import public_site
import admin as admin_module

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


TEST_MEMBER_ID = 999401


def make_member():
    with sqlite3.connect(database.DB_PATH) as conn:
        conn.execute("DELETE FROM members WHERE id=? OR email=?", (TEST_MEMBER_ID, "qa-rematch-scope@example.com"))
        conn.execute(
            "INSERT INTO members (id, full_name,email,phone,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,datetime('now'),'active',0,'[]')",
            (TEST_MEMBER_ID, "QA Rematch Scope", "qa-rematch-scope@example.com", "0500000001", "x"),
        )
        conn.commit()


def make_trip(trip_id, answers):
    with sqlite3.connect(database.DB_PATH) as conn:
        conn.execute("DELETE FROM trip_requests WHERE id=?", (trip_id,))
        conn.execute(
            "INSERT INTO trip_requests (id, member_id, request_name, travel_window, status, answers_json, created_at) "
            "VALUES(?,?,?,?,?,?,datetime('now'))",
            (trip_id, TEST_MEMBER_ID, "ליסבון", "2027-03-21 - 2027-03-25", "active", json.dumps(answers, ensure_ascii=False)),
        )
        conn.commit()


def make_offer(price_ils, outbound, ret, stops=0, arrival_code="LIS", trip_id=None, observed_at=None):
    payload = {
        "destination_name": "ליסבון",
        "flight": {
            "departure_time": "08:00", "arrival_time": "12:00",
            "return_departure_time": "14:00", "return_arrival_time": "18:00",
            "stops": stops,
            "baggage": {"carry_on_8kg": {"included": True}, "checked_bag_23kg": {"included": True}},
        },
    }
    observed_at = observed_at or datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(database.DB_PATH) as conn:
        cur = conn.execute(
            "INSERT INTO scan_runs (started_at, status, searches_planned, trip_id, finished_at) "
            "VALUES (?, 'success', 1, ?, ?)",
            (observed_at, trip_id, observed_at),
        )
        scan_run_id = cur.lastrowid
        cur = conn.execute(
            """INSERT INTO offers (scan_run_id, observed_at, route, departure_code, arrival_code, outbound_date,
               return_date, price_ils, score, score_label, departure_time, arrival_time, payload_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (scan_run_id, observed_at, f"TLV-{arrival_code}", "TLV", arrival_code, outbound, ret,
             price_ils, 70, "good", "08:00", "12:00", json.dumps(payload, ensure_ascii=False)),
        )
        offer_id = int(cur.lastrowid)
        conn.execute(
            "INSERT OR IGNORE INTO scan_run_offers(scan_run_id,offer_id,observed_at) VALUES(?,?,?)",
            (scan_run_id, offer_id, observed_at),
        )
        conn.commit()
        return offer_id, scan_run_id


def cleanup():
    with sqlite3.connect(database.DB_PATH) as conn:
        conn.execute("DELETE FROM trip_requests WHERE member_id=?", (TEST_MEMBER_ID,))
        conn.execute("DELETE FROM members WHERE id=?", (TEST_MEMBER_ID,))
        conn.commit()


make_member()

TRIP_ANSWERS = {
    "destinations": "LIS", "origin_airports": ["TLV"],
    "date_mode": "exact", "departure_date": "2027-03-21", "return_date": "2027-03-25",
    "date_flex_days": 0, "duration_days": 5,
    "deal_priorities": ["direct"],
    "vacation_type": "standard",
    "_flight_search_finished": True,
}
_future_out = (datetime.now(timezone.utc) + timedelta(days=200)).date().isoformat()
_future_ret = (datetime.now(timezone.utc) + timedelta(days=204)).date().isoformat()
_past_out = (datetime.now(timezone.utc) - timedelta(days=10)).date().isoformat()
_past_ret = (datetime.now(timezone.utc) - timedelta(days=6)).date().isoformat()

# =====================================================================
# 1. Scoping: rematch finds a trip's own offer via its own scan_run, even
#    when an UNRELATED trip's own scan_run also exists with different
#    offers - never a blanket cross-trip inventory call.
# =====================================================================
TRIP_A, TRIP_B = 770001, 770002
make_trip(TRIP_A, dict(TRIP_ANSWERS))
make_trip(TRIP_B, dict(TRIP_ANSWERS))
offer_a, run_a = make_offer(1700, _future_out, _future_ret, stops=1, trip_id=TRIP_A)
offer_b, run_b = make_offer(1900, _future_out, _future_ret, stops=1, trip_id=TRIP_B)

inv_a = public_site._inventory_for_trip_scan_run(TRIP_A)
inv_b = public_site._inventory_for_trip_scan_run(TRIP_B)
check("trip A's own inventory contains only trip A's own offer",
      [o.get("id") for o in inv_a] == [offer_a])
check("trip B's own inventory contains only trip B's own offer - not "
      "trip A's, even though both scans ran around the same time",
      [o.get("id") for o in inv_b] == [offer_b])

result_a = public_site.rematch_trip_without_new_scan(TRIP_A)
check("rematch for trip A succeeds using only its own scan_run's offer",
      result_a.get("status") == "success" and result_a.get("pinned") is True)
with sqlite3.connect(database.DB_PATH) as conn:
    conn.row_factory = sqlite3.Row
    saved_a = json.loads(conn.execute("SELECT answers_json FROM trip_requests WHERE id=?", (TRIP_A,)).fetchone()["answers_json"])
check("trip A ends up pinned to ITS OWN offer, never trip B's",
      saved_a.get("_matched_offer_ids") == [offer_a])

# =====================================================================
# 2. Past-date exclusion: an offer whose own flight date has already
#    passed is never shown, even though it's still sitting in the scan's
#    own scan_run_offers results.
# =====================================================================
TRIP_C = 770003
make_trip(TRIP_C, dict(TRIP_ANSWERS))
offer_c_past, _ = make_offer(1500, _past_out, _past_ret, stops=1, trip_id=TRIP_C)
inv_c = public_site._inventory_for_trip_scan_run(TRIP_C)
check("an offer whose flight date already passed is excluded from the "
      "rematch inventory entirely",
      inv_c == [])
result_c = public_site.rematch_trip_without_new_scan(TRIP_C)
check("rematch for a trip whose only offer is already in the past finds "
      "nothing to pin - never shows a stale offer",
      result_c.get("status") == "success" and result_c.get("pinned") is False)

# =====================================================================
# 3b. Shlomo's explicit follow-up check (20.10, after reviewing this very
#     fix, before it was pushed): recent_offers(offer_ids=...) itself adds
#     no age filter at all (confirmed directly against its own SQL), but
#     the shared matching tiers (_customer_deal_choices and friends) still
#     unconditionally enforced the SAME blanket 48h _offer_is_recent cutoff
#     that _inventory_for_trip_scan_run was built to get away from - an
#     offer whose flight date is still safely in the future, but whose own
#     scan is already more than 48 hours old (exactly vacation 259's own
#     real situation once 21.10 05:30 UTC passes), would still have been
#     silently dropped by every one of those four tiers, undoing the whole
#     scoping fix. Fixed via a require_recent=False thread-through, used
#     only by this rematch path.
# =====================================================================
TRIP_STALE = 770005
make_trip(TRIP_STALE, dict(TRIP_ANSWERS))
_stale_observed_at = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
offer_stale, _ = make_offer(
    1600, _future_out, _future_ret, stops=1, trip_id=TRIP_STALE, observed_at=_stale_observed_at
)
inv_stale = public_site._inventory_for_trip_scan_run(TRIP_STALE)
check("an offer observed 3 days ago (well past the blanket 48h window) but whose "
      "flight date is still in the future IS present in the scan_run-scoped inventory",
      [o.get("id") for o in inv_stale] == [offer_stale])
result_stale = public_site.rematch_trip_without_new_scan(TRIP_STALE)
check("Shlomo's explicit regression: rematch against a vacation whose own scan is "
      "older than 48 hours still succeeds and pins its own offer - the matching "
      "tiers no longer re-apply the blanket 48h freshness cutoff on this path",
      result_stale.get("status") == "success" and result_stale.get("pinned") is True)
with sqlite3.connect(database.DB_PATH) as conn:
    conn.row_factory = sqlite3.Row
    saved_stale = json.loads(conn.execute("SELECT answers_json FROM trip_requests WHERE id=?", (TRIP_STALE,)).fetchone()["answers_json"])
check("the stale-scan trip ends up pinned to its own (3-day-old-scan) offer",
      saved_stale.get("_matched_offer_ids") == [offer_stale])

# Regression: the ORDINARY customer-scan path (the shared 48h inventory
# pool, require_recent defaulting True) must still enforce the blanket
# freshness cutoff exactly as before - this fix must never loosen it there.
# inv_stale's own offer already carries its genuine 3-day-old last_seen_at/
# scan_started_at straight from the DB (set via make_offer's observed_at
# above) - no need to fake it a second time here.
with sqlite3.connect(database.DB_PATH) as conn:
    conn.row_factory = sqlite3.Row
    _trip_stale_row = conn.execute("SELECT * FROM trip_requests WHERE id=?", (TRIP_STALE,)).fetchone()
_trip_stale_dict = public_site._trip_dict(_trip_stale_row)
check("regression: the ordinary (non-rematch) tiers still default to "
      "require_recent=True and still exclude a >48h-old offer from that shared path",
      not public_site._customer_deal_choices(inv_stale, _trip_stale_dict, limit=5))

# =====================================================================
# 3. A trip with no scan_run tied to it at all (never went through the
#    tracked customer-scan path) gets a clear, honest error - never a
#    silent "success" that pinned nothing.
# =====================================================================
TRIP_D = 770004
make_trip(TRIP_D, dict(TRIP_ANSWERS))
result_d = public_site.rematch_trip_without_new_scan(TRIP_D)
check("a trip with no scan_run at all gets an explicit error, not a "
      "silently-empty success",
      result_d.get("status") == "error")

# =====================================================================
# 4. The admin.py /admin/scans template: the rematch button appears only
#    for a finished scan carrying a trip_id, and is wired to the real
#    route with no token anywhere in its own markup.
# =====================================================================
dashboard_source = open(admin_module.__file__, encoding="utf-8").read()
check("admin.py's scans table renders a rematch button form",
      'action="/admin/rematch-trip"' in dashboard_source)
check("the button only renders when the scan actually finished "
      "(s.finished_at) and carries a trip_id",
      "s.finished_at" in dashboard_source and 's.trip_id' in dashboard_source)
check("the button's own form never embeds a token in its markup - it "
      "relies purely on the authenticated admin session",
      "token" not in dashboard_source.split('action="/admin/rematch-trip"')[1].split("</form>")[0])
check("the button stops its click from also toggling the row's own "
      "expand/collapse handler",
      "event.stopPropagation()" in dashboard_source.split('action="/admin/rematch-trip"')[1][:400])

cleanup()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL VACATION-REMATCH-SCAN-RUN-SCOPED TESTS PASSED")
