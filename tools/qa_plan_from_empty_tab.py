"""QA: the "plan this part" button on an empty tab (the business owner, 23.10,
via Shlomo): flights / lodging / car / itinerary, with nothing in it -> one
button back to the chat, /trip/new?trip=<id>&plan=flights|lodging|car|route:
  "לחפש טיסות לחופשה זו" / "Find flights for this trip"
  "לתכנן לינה לחופשה זו" / "Plan lodging for this trip"
  "לתכנן רכב לחופשה זו" / "Plan a car for this trip"
  "לתכנן מסלול לחופשה זו" / "Plan an itinerary for this trip"
The chat side is Bezalel's - until it's ready the button is hidden
(PLAN_FROM_EMPTY_TAB_ENABLED, off by default).

Offline. Run: python3 tools/qa_plan_from_empty_tab.py
"""
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")
os.environ.pop("PLAN_FROM_EMPTY_TAB_ENABLED", None)

import database  # noqa: E402
database.init_db()

import app as app_module  # noqa: E402
import public_site  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

client = app_module.app.test_client()
FAILED = []
EMAIL = "qa-plan-from-tab@example.com"


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


def page(answers, lang="he"):
    with sqlite3.connect(database.DB_PATH) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (EMAIL,))
        member_id = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) VALUES(?,?,?,?,?,?,?)",
            ("QA", EMAIL, generate_password_hash("x"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        ).lastrowid
        trip_id = conn.execute("INSERT INTO trip_requests (member_id, request_name, status, answers_json, created_at) VALUES (?,?,?,?,datetime('now'))",
                               (member_id, "QA Plan", "active", json.dumps(answers, ensure_ascii=False))).lastrowid
        conn.commit()
    with client.session_transaction() as sess:
        sess["member_id"] = member_id
    return client.get(f"/account?lang={lang}").get_data(as_text=True), trip_id


EMPTY = {"destinations": "LIS", "departure_date": "2027-05-01", "return_date": "2027-05-08", "adults": 2,
         "_requested_services": ["flights"], "_flight_search_finished": True}
LINK = re.compile(r'href="/trip/new\?trip=(\d+)&amp;plan=(\w+)"[^>]*>([^<]+)</a>')

with patch.object(public_site, "_lodging_partner_cards", return_value=[]), patch.object(public_site, "_car_partner_cards", return_value=[]):
    html, _ = page(EMPTY)
    check("flag off (default): no plan button anywhere", "plan-from-tab-btn" not in html and "/trip/new?trip=" not in html)
    with patch.dict(os.environ, {"PLAN_FROM_EMPTY_TAB_ENABLED": "1"}):
        html, trip_id = page(EMPTY)
        en, trip_en = page(EMPTY, lang="en")
    found = {plan: (int(tid), label) for tid, plan, label in LINK.findall(html)}
    found_en = {plan: label for _, plan, label in LINK.findall(en)}
check("flag on: one button per empty tab - flights, lodging, car, itinerary", set(found) == {"flights", "lodging", "car", "route"})
check("each button carries this vacation's id", all(tid == trip_id for tid, _ in found.values()))
check("HE labels", {p: l for p, (_, l) in found.items()} == {"flights": "לחפש טיסות לחופשה זו", "lodging": "לתכנן לינה לחופשה זו",
                                                          "car": "לתכנן רכב לחופשה זו", "route": "לתכנן מסלול לחופשה זו"})
check("EN labels", found_en == {"flights": "Find flights for this trip", "lodging": "Plan lodging for this trip",
                                "car": "Plan a car for this trip", "route": "Plan an itinerary for this trip"})

with patch.object(public_site, "_lodging_partner_cards", return_value=[]), patch.object(public_site, "_car_partner_cards", return_value=[]), \
        patch.dict(os.environ, {"PLAN_FROM_EMPTY_TAB_ENABLED": "1"}):
    html, _ = page(dict(EMPTY, _flight_search_finished=False))
check("flights requested and still searching -> no flights button (nothing is missing yet)",
      "plan=flights" not in html and "plan=lodging" in html)
STAY = {"name": "Booking.com", "supplier": "Booking.com", "link": "https://example.com/stay", "dates": "", "guests": ""}
with patch.object(public_site, "_lodging_partner_cards", return_value=[STAY]), patch.object(public_site, "_car_partner_cards", return_value=[]), \
        patch.dict(os.environ, {"PLAN_FROM_EMPTY_TAB_ENABLED": "1"}):
    html, _ = page(EMPTY)
check("a tab with something in it (a lodging partner card) -> no plan button there", "plan=lodging" not in html)

with sqlite3.connect(database.DB_PATH) as conn:
    conn.execute("DELETE FROM members WHERE email=?", (EMAIL,))
    conn.commit()

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
