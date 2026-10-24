"""QA: the "חורג מהתקציב המועדף ב-X ₪" note on the deal card (live round 13 F,
24.10, Shlomo-approved).

The card template already had the note, but nothing ever set
budget_overage_ils - a customer whose offers were all above budget only saw
"לא כולל: תקציב", never by how much. Now _resolved_trip_offers (the one place
every vacation's offers pass through, already-finished ones included) sets it:
- per person, ILS, against the customer's own stated budget (without the
  agreed 10% tolerance);
- only for an offer that misses the budget (beyond the tolerance);
- only when the budget is the ONE condition the offer misses - the note also
  says "but a strong match for the rest of your preferences".

Offline. Run: python3 tools/qa_budget_overage_note.py
"""
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import database  # noqa: E402
database.init_db()

import app as app_module  # noqa: E402
import public_site  # noqa: E402

FAILED = []
MEMBER_ID = 990771


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


def trip(trip_id, answers, offer_ids):
    answers = dict(answers, _flight_search_finished=True, _matched_offer_ids=offer_ids)
    with sqlite3.connect(database.DB_PATH) as conn:
        conn.execute("DELETE FROM trip_requests WHERE id=?", (trip_id,))
        conn.execute("INSERT INTO trip_requests (id, member_id, request_name, travel_window, status, answers_json, created_at) "
                     "VALUES(?,?,?,?,?,?,datetime('now'))",
                     (trip_id, MEMBER_ID, "המבורג", "2027-05-06 - 2027-05-10", "active", json.dumps(answers, ensure_ascii=False)))
        conn.commit()
        conn.row_factory = sqlite3.Row
        return public_site._trip_dict(conn.execute("SELECT * FROM trip_requests WHERE id=?", (trip_id,)).fetchone())


def offer(price, stops=0):
    payload = {"destination_name": "המבורג", "flight": {"departure_time": "08:00", "arrival_time": "12:00",
               "return_departure_time": "14:00", "return_arrival_time": "18:00", "stops": stops,
               "baggage": {"carry_on_8kg": {"included": True}}}}
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(database.DB_PATH) as conn:
        run = conn.execute("INSERT INTO scan_runs (started_at, status, searches_planned, finished_at) VALUES (?, 'success', 1, ?)",
                           (now, now)).lastrowid
        oid = conn.execute(
            """INSERT INTO offers (scan_run_id, observed_at, route, departure_code, arrival_code, outbound_date, return_date,
               price_ils, score, score_label, departure_time, arrival_time, stops, payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run, now, "TLV-HAM", "TLV", "HAM", "2027-05-06", "2027-05-10", price, 70, "good", "08:00", "12:00", stops,
             json.dumps(payload, ensure_ascii=False))).lastrowid
        conn.execute("INSERT OR IGNORE INTO scan_run_offers(scan_run_id,offer_id,observed_at) VALUES(?,?,?)", (run, oid, now))
        conn.commit()
    return int(oid)


BASE = {"destinations": "HAM", "origin_airports": ["TLV"], "date_mode": "exact", "departure_date": "2027-05-06",
        "return_date": "2027-05-10", "vacation_type": "standard", "adults": 2, "children": 0,
        "budget_mode": "limited", "budget_amount": 1200, "budget_currency": "ILS"}

over, within_tol, both = offer(1548), offer(1300), offer(1548, stops=1)


def resolved(answers, ids, tid):
    t = trip(tid, answers, ids)
    return {o["id"]: o for o in public_site._resolved_trip_offers(database.recent_offers(limit=100, offer_ids=ids), t, limit=5)}


r = resolved(BASE, [over, within_tol], 990772)
check("round 13 Hamburg: 1,548 per person vs a 1,200 budget -> 348 ₪ over (against the stated budget, no tolerance)",
      r[over].get("budget_overage_ils") == 348)
check("an offer within the 10% tolerance (1,300 vs 1,320) -> no overage note (it's a budget match)",
      r[within_tol].get("budget_overage_ils") is None)
r2 = resolved(dict(BASE, deal_priorities=["direct"]), [both], 990773)
check("an offer that misses another condition too (not direct) -> no note (it claims 'a strong match for the rest')",
      r2[both].get("budget_overage_ils") is None and "תקציב" in r2[both].get("request_missed_reasons", []))
r3 = resolved(dict(BASE, budget_mode="unlimited", budget_amount=None), [over], 990774)
check("no budget -> no note", r3[over].get("budget_overage_ils") is None)
r4 = resolved(dict(BASE, budget_amount=300, budget_currency="EUR"), [over], 990775)
check("a foreign-currency budget is converted first (300 EUR ≈ 1,200 ₪) -> 348", r4[over].get("budget_overage_ils") == 348)

with app_module.app.test_request_context("/"):
    he = app_module.app.jinja_env.from_string('{% from "_deal_card.html" import deal_card %}{{ deal_card(o, "he") }}').render(o=r[over])
    en = app_module.app.jinja_env.from_string('{% from "_deal_card.html" import deal_card %}{{ deal_card(o, "en") }}').render(o=r[over])
check("the card shows the note in Hebrew", "חורג מהתקציב המועדף ב־348 ₪" in he)
check("and in English", "Above your preferred budget by" in en and "348" in en)

with sqlite3.connect(database.DB_PATH) as conn:
    conn.execute("DELETE FROM trip_requests WHERE member_id=?", (MEMBER_ID,))
    conn.commit()

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
