"""(22.10: every test hotel carries a booking link - a result without one is no longer shown, see
tools/qa_lodging_book_button.py.)

QA for lodging revenue item 4 (22.10, on top of PR #147): the lodging
results (lodging_offers) on the account page are grouped by stop + dates,
with a heading per group.

The server already searches each lodging.details.location_segments stop
separately and tags its hotels with segment_location/segment_dates, in route
order (public_site._run_lodging_search) - only the template changed:
  - consecutive hotels with the same stop+dates form one group, one heading
    ("<stop> · DD.MM.YYYY – DD.MM.YYYY");
  - untagged results (the usual single search, location_segments empty) are
    one group: the destination + the trip's own dates.
location_segments staying empty on a real multi-stop route is a known,
separate limitation - not touched here.

Offline (account page rendered with stored lodging_offers). Run:
python3 tools/qa_lodging_results_grouped.py
"""
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import database  # noqa: E402
database.init_db()

import app as app_module  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

client = app_module.app.test_client()
FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


def page(email, answers):
    with sqlite3.connect(database.DB_PATH) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        member_id = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA", email, generate_password_hash("x"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        ).lastrowid
        conn.execute("INSERT INTO trip_requests (member_id, request_name, status, answers_json, created_at) "
                     "VALUES (?,?,?,?,datetime('now'))", (member_id, "QA Lodging Groups", "active", json.dumps(answers, ensure_ascii=False)))
        conn.commit()
    with client.session_transaction() as sess:
        sess["member_id"] = member_id
    return client.get("/account").get_data(as_text=True)


def headings(html):
    return re.findall(r'<h4 class="lodging-results-group-title">([^<]*)</h4>', html)


BASE = {"destinations": "FCO", "departure_date": "2027-05-01", "return_date": "2027-05-08", "adults": 2,
        "lodging_type": "מלון", "_requested_services": ["lodging"]}

# --- Multi-stop: grouped by stop + dates, in route order ------------------------------------------------
html = page("qa-lodging-groups-multi@example.com", dict(BASE, lodging_offers=[
    {"name": "Roma A", "link": "https://hotel.example/Roma-A", "segment_location": "רומא", "segment_dates": "2027-05-01 – 2027-05-04"},
    {"name": "Roma B", "link": "https://hotel.example/Roma-B", "segment_location": "רומא", "segment_dates": "2027-05-01 – 2027-05-04"},
    {"name": "Firenze A", "link": "https://hotel.example/Firenze-A", "segment_location": "פירנצה", "segment_dates": "2027-05-04 – 2027-05-08"},
]))
h = headings(html)
check("multi-stop: one heading per stop, in route order", h == ["רומא · 01.05.2027 – 04.05.2027", "פירנצה · 04.05.2027 – 08.05.2027"])
check("multi-stop: each stop's hotels sit under its own heading",
      html.index("רומא · 01.05.2027") < html.index("Roma A") < html.index("Roma B") < html.index("פירנצה · 04.05.2027") < html.index("Firenze A"))
check("the old per-card segment line is gone (the heading replaces it)", "lodging-result-segment" not in html)

# --- Same stop twice with different dates -> two groups -----------------------------------------------
html = page("qa-lodging-groups-return@example.com", dict(BASE, lodging_offers=[
    {"name": "Roma 1", "link": "https://hotel.example/Roma-1", "segment_location": "רומא", "segment_dates": "2027-05-01 – 2027-05-03"},
    {"name": "Napoli", "link": "https://hotel.example/Napoli", "segment_location": "נאפולי", "segment_dates": "2027-05-03 – 2027-05-06"},
    {"name": "Roma 2", "link": "https://hotel.example/Roma-2", "segment_location": "רומא", "segment_dates": "2027-05-06 – 2027-05-08"},
]))
check("a stop visited twice (different dates) -> two separate groups",
      headings(html) == ["רומא · 01.05.2027 – 03.05.2027", "נאפולי · 03.05.2027 – 06.05.2027", "רומא · 06.05.2027 – 08.05.2027"])

# --- No segments (the usual case): one group, destination + trip dates --------------------------------
html = page("qa-lodging-groups-single@example.com", dict(BASE, lodging_offers=[{"name": "Hotel One", "link": "https://hotel.example/Hotel-One"}, {"name": "Hotel Two", "link": "https://hotel.example/Hotel-Two"}]))
h = headings(html)
check("no segments: exactly one heading", len(h) == 1)
# The destination part is the trip card's own display name (trip.destination_display - "איטליה" for FCO).
check("no segments: the heading is the destination (trip display name) + the trip's dates",
      h == ["איטליה · 01.05.2027 – 08.05.2027"])
check("no segments: every hotel still renders", "Hotel One" in html and "Hotel Two" in html)

# --- Unchanged parts --------------------------------------------------------------------------------------
html = page("qa-lodging-groups-empty@example.com", dict(BASE))
check("no results yet: no group heading, no search button, a plain empty-state line (like the car tab)",
      not headings(html) and "חיפוש לינה אמיתית" not in html and "כאן יוצגו אפשרויות לינה" in html)

with sqlite3.connect(database.DB_PATH) as conn:
    conn.execute("DELETE FROM members WHERE email LIKE 'qa-lodging-groups-%'")
    conn.commit()

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
