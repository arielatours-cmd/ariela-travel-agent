"""QA for the business owner's explicit instruction (2026-10-14, after
Shaked's real-scan + duplicate-vacation testing on trip 209): the
duplicate-scan guard must trigger the moment the customer approved
("מאשר"/"מאשרת") and the system actually launched a real scan - not rely on
the client's own combined_search_launched flag alone (which only reflects
what THIS persisted conversation believes, not reality), and must look back
90 days. When found, the chat must never just keep going as if still
mid-planning (and never auto-navigate to a finished trip's waiting page) -
it redirects straight to the existing vacation with the paid daily-tracking
mention, and resets the conversation.

This tests _find_recent_scanned_vacation directly against the real schema
(inserting and cleaning up its own rows), mirroring the house convention
already used by tools/qa_booking_lifecycle_cj.py and friends.

Run: python3 tools/qa_duplicate_scan_90day_guard.py
"""
import sys
import os
import sqlite3
import json
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()
import ariella_chat_clean as chat

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


TEST_MEMBER_ID = 999001


def make_member():
    with sqlite3.connect(database.DB_PATH) as conn:
        conn.execute("DELETE FROM members WHERE id=?", (TEST_MEMBER_ID,))
        conn.execute(
            "INSERT INTO members (id, full_name,email,phone,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,datetime('now'),'active',0,'[]')",
            (TEST_MEMBER_ID, "QA Duplicate Guard", "qa-dup-guard@example.com", "0500000000", "x"),
        )
        conn.commit()


def make_trip(trip_id, created_at, destinations, dep, ret, origin="TLV", status="active"):
    answers = {
        "origin_airports": [origin],
        "destinations": destinations,
        "date_mode": "exact",
        "departure_date": dep,
        "return_date": ret,
    }
    with sqlite3.connect(database.DB_PATH) as conn:
        conn.execute("DELETE FROM trip_requests WHERE id=?", (trip_id,))
        conn.execute(
            "INSERT INTO trip_requests (id, member_id, request_name, travel_window, status, answers_json, created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (trip_id, TEST_MEMBER_ID, "קפריסין", f"{dep} – {ret}", status, json.dumps(answers, ensure_ascii=False), created_at),
        )
        conn.commit()


def cleanup():
    with sqlite3.connect(database.DB_PATH) as conn:
        conn.execute("DELETE FROM trip_requests WHERE member_id=?", (TEST_MEMBER_ID,))
        conn.execute("DELETE FROM members WHERE id=?", (TEST_MEMBER_ID,))
        conn.commit()


make_member()
now = datetime.now(timezone.utc)

# --- 1. The exact qa-s89 shape: a matching vacation scanned 10 days ago
#        (well within the 90-day window) is found ---
make_trip(5001001, (now - timedelta(days=10)).isoformat(), "LCA,PFO", "2026-12-06", "2026-12-11")
found = chat._find_recent_scanned_vacation(TEST_MEMBER_ID, ["LCA", "PFO"], "TLV", "2026-12-06", "2026-12-11")
check("a matching vacation scanned 10 days ago is found", found == (5001001, "קפריסין"))

# --- 2. Outside the 90-day window -> never found, even with an otherwise
#        exact match (the business owner's own explicit cutoff) ---
make_trip(5001002, (now - timedelta(days=120)).isoformat(), "LCA,PFO", "2026-12-06", "2026-12-11")
with sqlite3.connect(database.DB_PATH) as conn:
    conn.execute("DELETE FROM trip_requests WHERE id=?", (5001001,))
    conn.commit()
found_old = chat._find_recent_scanned_vacation(TEST_MEMBER_ID, ["LCA", "PFO"], "TLV", "2026-12-06", "2026-12-11")
check("a vacation scanned 120 days ago (outside the 90-day window) is never found", found_old is None)

# --- 3. Different dates for the same destination -> not a match (a
#        genuinely new request must never be blocked) ---
make_trip(5001003, (now - timedelta(days=5)).isoformat(), "LCA,PFO", "2026-12-06", "2026-12-11")
found_diff_dates = chat._find_recent_scanned_vacation(TEST_MEMBER_ID, ["LCA", "PFO"], "TLV", "2027-01-10", "2027-01-15")
check("a genuinely different travel date for the same destination is never blocked",
      found_diff_dates is None)

# --- 4. Different destination, same dates -> not a match ---
found_diff_dest = chat._find_recent_scanned_vacation(TEST_MEMBER_ID, ["ATH"], "TLV", "2026-12-06", "2026-12-11")
check("a genuinely different destination for the same dates is never blocked",
      found_diff_dest is None)

# --- 5. A different member's identical trip is never matched (per-member
#        isolation) ---
found_other_member = chat._find_recent_scanned_vacation(TEST_MEMBER_ID + 1, ["LCA", "PFO"], "TLV", "2026-12-06", "2026-12-11")
check("a different member's identical trip is never matched", found_other_member is None)

# --- 6. Missing destination codes or dates -> never crashes, returns None ---
check("empty destination codes -> None, never crashes",
      chat._find_recent_scanned_vacation(TEST_MEMBER_ID, [], "TLV", "2026-12-06", "2026-12-11") is None)
check("missing dates -> None, never crashes",
      chat._find_recent_scanned_vacation(TEST_MEMBER_ID, ["LCA"], "TLV", None, None) is None)

cleanup()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DUPLICATE-SCAN 90-DAY GUARD TESTS PASSED")
