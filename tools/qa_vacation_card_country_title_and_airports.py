"""QA for Shlomo/Carmit's background-priority fix (after PR #55 landed):
the vacation-page trip card title showed airport CITY names instead of the
destination COUNTRY (e.g. "דוברובניק • ספליט" for a Croatia trip with
DBV+SPU gateways, instead of "קרואטיה"), and the "פרטי הבקשה" (request
details) panel had no way to see which airports the search actually used
for landing/return.

Root cause (title): public_site.py's account() view built
trip["destination_display"] by joining each destination airport's
city_he/city_en - never looked at the airport's own country_he/country_en
fields, which the shipped static/airports.json catalog already has for
every entry. Fixed by joining (deduped) country names instead, with city
name/code as a defensive fallback if a catalog entry is ever missing a
country field.

Also added two new lines to the request-details panel (templates/
account.html): "שדה נחיתה" (landing airport, from answers['destinations'])
and "שדה המראה בחזור" (return departure airport, from answers
['return_departure_airports']) - mirroring the existing "שדה יציאה" row's
raw-IATA-code display style.

Run: python3 tools/qa_vacation_card_country_title_and_airports.py
"""
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

import app as app_module
from werkzeug.security import generate_password_hash

DB = database.DB_PATH
client = app_module.app.test_client()

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA Vacation Card", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def _make_trip(member_id, answers, request_name="חופשה"):
    with sqlite3.connect(DB) as conn:
        cur = conn.execute(
            "INSERT INTO trip_requests (member_id, request_name, created_at, status, answers_json) VALUES(?,?,?,?,?)",
            (member_id, request_name, datetime.now(timezone.utc).isoformat(), "active", json.dumps(answers, ensure_ascii=False)),
        )
        return cur.lastrowid


member_id = _make_member("qa-vacation-card@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id

# --- 1. The exact live bug: multi-gateway Croatia trip (DBV + SPU, both
#        in the same country) must show the country, not two city names ---
trip1 = _make_trip(member_id, {
    "origin_airports": ["TLV"], "destinations": "DBV,SPU",
    "return_departure_airports": ["DBV"],
    "departure_date": "2027-09-19", "return_date": "2027-09-30",
    "adults": 2,
})
r1 = client.get("/account")
html1 = r1.get_data(as_text=True)
check("multi-gateway same-country trip shows the country name (קרואטיה)",
      "קרואטיה" in html1)
check("multi-gateway same-country trip no longer shows city names joined with bullets",
      "דוברובניק • ספליט" not in html1 and "ספליט • דוברובניק" not in html1)
check("the new landing-airport line shows both raw codes",
      "שדה נחיתה" in html1 and "DBV, SPU" in html1)
check("the new return-departure-airport line shows the right code",
      "שדה המראה בחזור" in html1 and "DBV" in html1)

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM trip_requests WHERE id=?", (trip1,))
    conn.commit()

# --- 2. Regression: a single-gateway trip still shows a single country
#        name exactly as before (no regression on the simple case) ---
trip2 = _make_trip(member_id, {
    "origin_airports": ["TLV"], "destinations": "FCO",
    "return_departure_airports": ["FCO"],
    "departure_date": "2026-11-10", "return_date": "2026-11-14",
    "adults": 2,
}, request_name="רומא")
r2 = client.get("/account")
html2 = r2.get_data(as_text=True)
check("single-gateway Rome trip shows the country name (איטליה)", "איטליה" in html2)

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM trip_requests WHERE id=?", (trip2,))
    conn.commit()

# --- 3. Regression: a trip with no destination airports yet (still being
#        planned) must not crash and must fall back to the request name ---
trip3 = _make_trip(member_id, {"origin_airports": ["TLV"], "adults": 2}, request_name="בקשה חדשה")
r3 = client.get("/account")
check("a trip with no destination airports yet does not crash the page",
      r3.status_code == 200)
html3 = r3.get_data(as_text=True)
check("a trip with no destination airports yet falls back to the request name",
      "בקשה חדשה" in html3)
check("a trip with no destination airports yet shows neither new airport line",
      "שדה נחיתה" not in html3.split("בקשה חדשה", 1)[-1][:2000] if "בקשה חדשה" in html3 else True)

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM trip_requests WHERE id=?", (trip3,))
    conn.commit()

# --- 4. Regression: a ski vacation's title is untouched (different code
#        path entirely, must not be affected by this change) ---
trip4 = _make_trip(member_id, {
    "vacation_type": "ski", "ski_target_labels": ["שאמוני"],
    "origin_airports": ["TLV"], "adults": 2,
}, request_name="סקי")
r4 = client.get("/account")
check("ski vacation title is untouched by the country-title change",
      "חופשת סקי — שאמוני" in r4.get_data(as_text=True))

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM trip_requests WHERE id=?", (trip4,))
    conn.commit()

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL VACATION-CARD-COUNTRY-TITLE-AND-AIRPORTS TESTS PASSED")
