"""QA for the vacation-tab mobile header wrap, per Shlomo's relay (22.10,
business owner): "אפשרויות לינה ליעד ולתאריכים שלכם" (the lodging tab's
header) broke onto two large lines on mobile. Fixed in templates/
account.html: the lodging h3 now holds both a full-text span (desktop) and
a shortened "אפשרויות לינה" span (mobile), toggled by a <=480px media query
that also shrinks every .vacation-panel h3's font-size a notch - covering
the other tab headers (flights/car/itinerary) too, in case any of them was
ever borderline, without changing their text (none of them were reported
broken, and all are short enough that the font-size alone is enough).

Run: python3 tools/qa_vacation_panel_mobile_header.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

import public_site
import app as app_module
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash
import sqlite3

DB = database.DB_PATH
client = app_module.app.test_client()

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


account_html_src = open(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "account.html"),
    encoding="utf-8",
).read()

check("the lodging h3 carries a full-text span with the original wording",
      '<span class="panel-title-full">אפשרויות לינה ליעד ולתאריכים שלכם</span>' in account_html_src)
check("the lodging h3 also carries a shortened mobile span",
      '<span class="panel-title-short">אפשרויות לינה</span>' in account_html_src)
check("the short span is hidden by default (desktop-first)",
      ".vacation-panel h3 .panel-title-short{display:none}" in account_html_src)
check("a <=480px media query flips full/short and shrinks the header font-size",
      "@media(max-width:480px)" in account_html_src
      and ".panel-title-full{display:none}" in account_html_src
      and ".panel-title-short{display:inline}" in account_html_src)
check("the header never wraps mid-word (nowrap) at any width",
      ".vacation-panel h3{white-space:nowrap}" in account_html_src)
check("the other tab headers (flights/car/itinerary) are untouched text-wise - no short span added to them",
      account_html_src.count('class="panel-title-short"') == 1)


def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA Mobile Header", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def _make_trip(member_id, answers):
    import json
    with sqlite3.connect(DB) as conn:
        cur = conn.execute(
            "INSERT INTO trip_requests (member_id, request_name, status, answers_json, created_at) "
            "VALUES (?,?,?,?,datetime('now'))",
            (member_id, "QA Mobile Header Trip", "active", json.dumps(answers, ensure_ascii=False)),
        )
        conn.commit()
        return int(cur.lastrowid)


member_id = _make_member("qa-mobile-header@example.com")
trip_id = _make_trip(member_id, {
    "destinations": "SOF", "departure_date": "2027-04-01", "return_date": "2027-04-08", "adults": 2,
})
with client.session_transaction() as sess:
    sess["member_id"] = member_id
resp = client.get("/account")
body = resp.get_data(as_text=True)
check("a real /account render still renders the lodging panel header with both spans intact",
      resp.status_code == 200
      and '<span class="panel-title-full">אפשרויות לינה ליעד ולתאריכים שלכם</span>' in body
      and '<span class="panel-title-short">אפשרויות לינה</span>' in body)

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE email='qa-mobile-header@example.com'")
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL VACATION-PANEL-MOBILE-HEADER TESTS PASSED")
