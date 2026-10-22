"""QA for the business owner's SECOND, broader finding on vacation 259
(20.10.2026, relayed by Shlomo, right after the budget-currency fix went in):
"the same applies to direct flight - the 'not direct' marking also doesn't
appear on 259's card, even though the flights aren't direct. Probably a
general problem carrying the markings to the card, not just budget. Check
every condition type (budget, direct, time, dates, length) end to end to
the HTML."

Confirmed, and it IS general: _resolved_trip_offers (the one function that
builds trip["offers"] for every /account page render) has two branches -
`fresh` (mid-search, via _customer_deal_choices, which DOES attach
request_missed_reasons/customer_choice_label_he at that moment) and
`pinned` (an ALREADY-FINISHED vacation - i.e. every ordinary page load of
every vacation after its initial search, ALWAYS this branch) - which just
re-fetches bare offer rows via recent_offers(offer_ids=saved_ids) and never
recomputed which selected condition (ANY of them - budget, direct,
connections, baggage, dates, trip length, time-of-day) the offer actually
misses. request_missed_reasons/customer_choice_label_he were only ever
attached transiently inside whichever tier function originally matched-and-
pinned the offer (_match_and_pin_initial_offers) - never persisted anywhere,
and never recomputed on a later render. The instant a vacation finishes its
search (true for virtually every vacation a customer actually looks at more
than once), every one of its condition mismatches silently stopped being
shown - not a budget-specific bug.

Fixed: _resolved_trip_offers now recomputes _objective_match_details for
EVERY offer (both branches) right before returning, and attaches
request_missed_reasons/customer_choice_label_he whenever something is
missed - the single choke point both branches pass through, so every
condition type is covered by one fix instead of one symptom at a time.

Run: python3 tools/qa_pinned_offer_condition_labels.py
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


TEST_MEMBER_ID = 999502


def make_member():
    with sqlite3.connect(database.DB_PATH) as conn:
        conn.execute("DELETE FROM members WHERE id=?", (TEST_MEMBER_ID,))
        conn.execute(
            "INSERT INTO members (id, full_name,email,phone,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,datetime('now'),'active',0,'[]')",
            (TEST_MEMBER_ID, "QA Pinned Labels", "qa-pinned-labels@example.com", "0500000003", "x"),
        )
        conn.commit()


def make_finished_trip(trip_id, answers, matched_offer_ids):
    answers = dict(answers)
    answers["_flight_search_finished"] = True
    answers["_matched_offer_ids"] = matched_offer_ids
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


def insert_real_offer(price_ils, stops, trip_id=None):
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
            "INSERT INTO scan_runs (started_at, status, searches_planned, trip_id, finished_at) "
            "VALUES (?, 'success', 1, ?, ?)",
            (observed_at, trip_id, observed_at),
        )
        scan_run_id = cur.lastrowid
        cur = conn.execute(
            """INSERT INTO offers (scan_run_id, observed_at, route, departure_code, arrival_code, outbound_date,
               return_date, price_ils, score, score_label, departure_time, arrival_time, stops, payload_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (scan_run_id, observed_at, "TLV-LIS", "TLV", "LIS", "2027-03-21", "2027-03-25",
             price_ils, 70, "good", "08:00", "12:00", stops, json.dumps(payload, ensure_ascii=False)),
        )
        offer_id = int(cur.lastrowid)
        conn.execute(
            "INSERT OR IGNORE INTO scan_run_offers(scan_run_id,offer_id,observed_at) VALUES(?,?,?)",
            (scan_run_id, offer_id, observed_at),
        )
        conn.commit()
        return offer_id


BASE_ANSWERS = {
    "destinations": "LIS", "origin_airports": ["TLV"],
    "date_mode": "exact", "departure_date": "2027-03-21", "return_date": "2027-03-25",
    "duration_days": 5, "deal_priorities": ["direct"], "vacation_type": "standard",
    "adults": 2, "children": 0,
}


def cleanup():
    with sqlite3.connect(database.DB_PATH) as conn:
        conn.execute("DELETE FROM trip_requests WHERE member_id=?", (TEST_MEMBER_ID,))
        conn.execute("DELETE FROM members WHERE id=?", (TEST_MEMBER_ID,))
        conn.commit()


make_member()

# =====================================================================
# Vacation 259's exact reported shape: an ALREADY-FINISHED vacation (every
# ordinary /account page load) with a non-direct offer pinned to it. The
# customer asked for a direct flight (deal_priorities=["direct"]).
# =====================================================================
non_direct_id = insert_real_offer(1800, stops=1, trip_id=990001)
trip_259_like = make_finished_trip(990001, BASE_ANSWERS, [non_direct_id])

offers = public_site._resolved_trip_offers(
    [_o for _o in database.recent_offers(limit=100, offer_ids=[non_direct_id])],
    trip_259_like, limit=5,
)
check("vacation 259's exact shape: a non-direct offer shown on an ALREADY-"
      "FINISHED vacation's card is correctly re-labeled 'not direct' on every "
      "render, not just at the moment it was first pinned",
      len(offers) == 1 and "טיסה ישירה" in offers[0].get("request_missed_reasons", []))
check("the mislabeled offer also carries a customer-visible label, so the "
      "template actually renders the missed-reason span at all",
      bool(offers[0].get("customer_choice_label_he")))

# =====================================================================
# Regression: a genuinely direct offer, pinned the same way, carries NO
# missed-reason and no label at all - this fix must never start labeling
# offers that actually satisfy every selected condition.
# =====================================================================
direct_id = insert_real_offer(1800, stops=0, trip_id=990002)
trip_direct = make_finished_trip(990002, BASE_ANSWERS, [direct_id])
offers_direct = public_site._resolved_trip_offers(
    [_o for _o in database.recent_offers(limit=100, offer_ids=[direct_id])],
    trip_direct, limit=5,
)
check("regression: a genuinely direct offer on an already-finished vacation "
      "carries no missed-reasons and no label at all",
      len(offers_direct) == 1 and not offers_direct[0].get("request_missed_reasons")
      and not offers_direct[0].get("customer_choice_label_he"))

# =====================================================================
# Every other condition type Shlomo named: budget (already covered by the
# currency fix, verified again here through the real display path), dates,
# and trip length - all must survive an already-finished vacation's render.
# =====================================================================
budget_answers = dict(BASE_ANSWERS, deal_priorities=[], budget_mode="limited", budget_amount=150, budget_currency="EUR")
over_budget_id = insert_real_offer(2800, stops=0, trip_id=990003)
trip_budget = make_finished_trip(990003, budget_answers, [over_budget_id])
offers_budget = public_site._resolved_trip_offers(
    [_o for _o in database.recent_offers(limit=100, offer_ids=[over_budget_id])],
    trip_budget, limit=5,
)
check("budget: an over-budget offer on an already-finished vacation is "
      "re-labeled 'תקציב' on every render",
      len(offers_budget) == 1 and "תקציב" in offers_budget[0].get("request_missed_reasons", []))

length_answers = dict(BASE_ANSWERS, deal_priorities=[], duration_days=7)
wrong_length_id = insert_real_offer(1800, stops=0, trip_id=990004)
trip_length = make_finished_trip(990004, length_answers, [wrong_length_id])
offers_length = public_site._resolved_trip_offers(
    [_o for _o in database.recent_offers(limit=100, offer_ids=[wrong_length_id])],
    trip_length, limit=5,
)
check("trip length: an offer with the wrong number of days on an already-"
      "finished vacation is re-labeled with the requested day count",
      len(offers_length) == 1 and bool(offers_length[0].get("request_missed_reasons")))

cleanup()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL PINNED-OFFER-CONDITION-LABELS TESTS PASSED")
