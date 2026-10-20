"""QA for Shaked's review finding on PR #95 (20.10.2026, relayed by Shlomo):
"In _match_and_pin_initial_offers, after merging tiers 2-4, `alternatives`
were sorted by price alone and only THEN sliced to [:5]. Result: a flight
that meets MORE of the customer's selected conditions but costs more can be
dropped from the card entirely just because five cheaper, worse-matching
flights filled the five slots first. Example: a direct flight at 1700 ILS
was dropped because there were 5 cheaper connecting flights."

This is a stricter bug than the DISPLAY-ORDER bug the business owner's
20.10 sorting directive already fixed in _resolved_trip_offers (that one
only re-orders whichever 5 offers already survived) - this one determines
WHICH 5 offers survive the slice in the first place, before any later
re-sort ever gets a chance to put the better match first.

Fixed by sharing _conditions_met_then_price_sort_key between
_resolved_trip_offers and _match_and_pin_initial_offers, and sorting
`alternatives` by it BEFORE slicing to 5, not by price alone.

Run: python3 tools/qa_alternatives_ranked_before_slice.py
"""
import os
import sys
import sqlite3
import json
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()
import public_site

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


TEST_MEMBER_ID = 999503


def make_member():
    with sqlite3.connect(database.DB_PATH) as conn:
        conn.execute("DELETE FROM members WHERE id=?", (TEST_MEMBER_ID,))
        conn.execute(
            "INSERT INTO members (id, full_name,email,phone,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,datetime('now'),'active',0,'[]')",
            (TEST_MEMBER_ID, "QA Alternatives Ranking", "qa-alternatives-ranking@example.com", "0500000004", "x"),
        )
        conn.commit()


def make_open_trip(trip_id, answers):
    with sqlite3.connect(database.DB_PATH) as conn:
        conn.execute("DELETE FROM trip_requests WHERE id=?", (trip_id,))
        conn.execute(
            "INSERT INTO trip_requests (id, member_id, request_name, travel_window, status, answers_json, created_at) "
            "VALUES(?,?,?,?,?,?,datetime('now'))",
            (trip_id, TEST_MEMBER_ID, "ליסבון", "2027-03-21 - 2027-03-25", "active", json.dumps(answers, ensure_ascii=False)),
        )
        conn.commit()
    with sqlite3.connect(database.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return public_site._trip_dict(conn.execute("SELECT * FROM trip_requests WHERE id=?", (trip_id,)).fetchone())


def insert_real_offer(price_ils, stops, baggage_included, departure_time="08:00"):
    # Each offer needs its OWN departure_time (or another _offer_signature
    # field) - several same-route/same-stops offers sharing one signature
    # would collapse into "the same observed flight at a different price"
    # during dedup, not five genuinely distinct flights.
    bag = (
        {"carry_on_8kg": {"included": True}, "checked_bag_23kg": {"included": True}}
        if baggage_included
        else {"carry_on_8kg": {"included": False}, "checked_bag_23kg": {"included": False}}
    )
    payload = {
        "destination_name": "ליסבון",
        "flight": {
            "departure_time": departure_time, "arrival_time": "12:00",
            "return_departure_time": "14:00", "return_arrival_time": "18:00",
            "stops": stops,
            "baggage": bag,
        },
    }
    observed_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(database.DB_PATH) as conn:
        cur = conn.execute(
            "INSERT INTO scan_runs (started_at, status, searches_planned, finished_at) "
            "VALUES (?, 'success', 1, ?)",
            (observed_at, observed_at),
        )
        scan_run_id = cur.lastrowid
        cur = conn.execute(
            """INSERT INTO offers (scan_run_id, observed_at, route, departure_code, arrival_code, outbound_date,
               return_date, price_ils, score, score_label, departure_time, arrival_time, stops, payload_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (scan_run_id, observed_at, "TLV-LIS", "TLV", "LIS", "2027-03-21", "2027-03-25",
             price_ils, 70, "good", departure_time, "12:00", stops, json.dumps(payload, ensure_ascii=False)),
        )
        offer_id = int(cur.lastrowid)
        conn.execute(
            "INSERT OR IGNORE INTO scan_run_offers(scan_run_id,offer_id,observed_at) VALUES(?,?,?)",
            (scan_run_id, offer_id, observed_at),
        )
        conn.commit()
        return offer_id


def cleanup():
    with sqlite3.connect(database.DB_PATH) as conn:
        conn.execute("DELETE FROM trip_requests WHERE member_id=?", (TEST_MEMBER_ID,))
        conn.execute("DELETE FROM members WHERE id=?", (TEST_MEMBER_ID,))
        conn.commit()


make_member()

# =====================================================================
# Reproduce Shaked's exact shape: a customer who asked for direct flights
# AND baggage, with a limited ILS budget (ceiling = 1300 * 1.10 = 1430).
#
# 5 cheap distractor offers (900-1300 ILS): non-direct, no baggage - miss
# BOTH selected conditions (direct, baggage), but are within budget and on
# the requested exact dates/length - matched count 3 of 5 possible
# (dates, duration, budget).
#
# 1 better-matching but pricier offer (1700 ILS): direct, with baggage -
# meets direct+baggage+dates+duration, only misses budget - matched count
# 4 of 5. It must survive the merge+slice despite costing more than all
# five distractors.
# =====================================================================
answers = {
    "destinations": "LIS", "origin_airports": ["TLV"],
    "date_mode": "exact", "departure_date": "2027-03-21", "return_date": "2027-03-25",
    "duration_days": 5, "deal_priorities": ["direct", "baggage"], "vacation_type": "standard",
    "adults": 2, "children": 0,
    "budget_mode": "limited", "budget_amount": 1300, "budget_currency": "ILS",
}
trip_id = 990101
trip = make_open_trip(trip_id, answers)

distractor_ids = [
    insert_real_offer(p, stops=1, baggage_included=False, departure_time=t)
    for p, t in zip((900, 1000, 1100, 1200, 1300), ("08:00", "08:05", "08:10", "08:15", "08:20"))
]
better_match_id = insert_real_offer(1700, stops=0, baggage_included=True, departure_time="09:00")

all_offers = list(database.recent_offers(limit=200, offer_ids=distractor_ids + [better_match_id]))
pinned = public_site._match_and_pin_initial_offers(trip_id, trip, answers, all_offers, require_recent=False)

check("something was pinned at all (fallback chain didn't come back empty)", pinned)

matched_ids = set(answers.get("_matched_offer_ids") or [])
check("the pricier but better-matching direct+baggage offer (1700) survives the "
      "merge+slice, instead of being pushed out by five cheaper, worse-matching "
      "flights sorted on price alone",
      better_match_id in matched_ids)
check("regression: still only 5 ids are pinned (the slice-to-5 cap itself still "
      "applies, just on the right ranking now)",
      len(matched_ids) == 5)
check("the most expensive distractor (1300, matched count 3) is the one bumped "
      "out in favor of the better match (4), not an arbitrary one",
      distractor_ids[-1] not in matched_ids and all(d in matched_ids for d in distractor_ids[:-1]))

cleanup()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL ALTERNATIVES-RANKED-BEFORE-SLICE TESTS PASSED")
