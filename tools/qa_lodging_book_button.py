"""QA for the lodging tab booking button (+ the business owner's item d:
a result with no booking link isn't shown at all; a group left with nothing
bookable shows only its heading + the dedicated partner card) (22.10, the business owner's
decision relayed by Shlomo/Bezalel - part 1 only; the grouping by the
route's lodging place is on hold, on its own branch):

Every hotel/apartment result has a "להזמנה" button (instead of only
"צפייה ופרטים") to the same hotel - a booking.com result already goes
through CJ (_wrap_booking_com_hotel_links, #147). Only a real CJ link is
labelled "קישור שותף", linking to the affiliate-disclosure page, with
rel=sponsored; a link to the hotel's own site / another OTA is not.

Offline. Run: python3 tools/qa_lodging_book_button.py
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

import database  # noqa: E402
database.init_db()

import public_site  # noqa: E402
import app as app_module  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


CJ = "https://www.anrdoezrs.net/click-qa-evergreen"
is_aff = public_site._is_affiliate_lodging_link
with patch.object(public_site, "CJ_BOOKING_EVERGREEN_LINK", CJ):
    wrapped = public_site._cj_booking_wrap("https://www.booking.com/hotel/pt/a.html", sid="trip1")
    check("a CJ-wrapped booking.com link is an affiliate link", is_aff(wrapped))
    check("a raw booking.com / hotel-site link is not", not is_aff("https://www.booking.com/hotel/pt/a.html")
          and not is_aff("https://hotel.example/book"))
    check("a look-alike that only starts with the CJ host is not", not is_aff(CJ + "-evil/x"))
with patch.object(public_site, "CJ_BOOKING_EVERGREEN_LINK", ""):
    check("no CJ link configured -> nothing is an affiliate link", not is_aff("https://www.booking.com/hotel/pt/a.html"))

offers = [
    {"name": "Booking A", "link": CJ + "?url=https%3A%2F%2Fwww.booking.com%2Fhotel%2Fpt%2Fa.html&sid=trip1"},
    {"name": "Own Site B", "link": "https://hotel-own-site.example/book"},
    {"name": "No Link C"},
]
answers = {"destinations": "LIS", "departure_date": "2027-03-21", "return_date": "2027-03-25", "adults": 2,
           "_requested_services": ["lodging"], "lodging_offers": offers}
with sqlite3.connect(database.DB_PATH) as conn:
    conn.execute("DELETE FROM members WHERE email='qa-lodging-book@example.com'")
    member_id = conn.execute(
        "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) VALUES(?,?,?,?,?,?,?)",
        ("QA", "qa-lodging-book@example.com", generate_password_hash("x"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
    ).lastrowid
    conn.execute("INSERT INTO trip_requests (member_id, request_name, status, answers_json, created_at) VALUES (?,?,?,?,datetime('now'))",
                 (member_id, "QA Lisbon", "active", json.dumps(answers, ensure_ascii=False)))
    conn.commit()
client = app_module.app.test_client()
with client.session_transaction() as sess:
    sess["member_id"] = member_id
with patch.object(public_site, "CJ_BOOKING_EVERGREEN_LINK", CJ):
    html = client.get("/account").get_data(as_text=True)
cards = dict(re.findall(r'<div class="lodging-result-info">\s*<strong>([^<]+)</strong>(.*?)</div>\s*</div>', html, re.S))
# (the dedicated partner card shares the card markup, so a subset check)
check("page: the two bookable results render", {"Booking A", "Own Site B"} <= set(cards))
check("page: a result with a link has a 'להזמנה' button to it",
      "להזמנה" in cards.get("Booking A", "") and "להזמנה" in cards.get("Own Site B", "") and "hotel-own-site.example/book" in cards.get("Own Site B", ""))
check("page: 'צפייה ופרטים' is gone from the lodging results", "צפייה ופרטים" not in "".join(cards.values()))
check("page: the CJ result is labelled 'קישור שותף' -> the disclosure page, rel=sponsored",
      "קישור שותף" in cards.get("Booking A", "") and "/affiliate-disclosure" in cards.get("Booking A", "") and "sponsored" in cards.get("Booking A", ""))
check("page: the hotel's own site is NOT labelled as an affiliate link",
      "קישור שותף" not in cards.get("Own Site B", "") and "sponsored" not in cards.get("Own Site B", ""))
check("page: a result with no booking link isn't shown at all (the business owner, 22.10)", "No Link C" not in html)
PCARD = 'class="lodging-result-card lodging-partner-card"'
check("page: bookable results -> the partner card stays above the list only (not repeated under a heading)",
      html.count(PCARD) <= 1 and (PCARD not in html or html.index(PCARD) < html.index("lodging-results-group-title")))

# --- A group left with nothing bookable: only its heading + the dedicated partner card -------------------
answers2 = dict(answers, lodging_offers=[{"name": "No Link X"}, {"name": "No Link Y"}])
with sqlite3.connect(database.DB_PATH) as conn:
    conn.execute("UPDATE trip_requests SET answers_json=? WHERE member_id=?", (json.dumps(answers2, ensure_ascii=False), member_id))
    conn.commit()
with patch.object(public_site, "CJ_BOOKING_EVERGREEN_LINK", CJ), patch.object(public_site, "LODGING_AFFILIATE_LINK", "https://partner.example/l"):
    html2 = client.get("/account").get_data(as_text=True)
headings2 = re.findall(r'<h4 class="lodging-results-group-title">([^<]*)</h4>', html2)
panel = html2.split('id="lodging-', 1)[1].split('class="vacation-panel"', 1)[0]
check("empty group: no linkless result is shown", "No Link X" not in html2 and "No Link Y" not in html2)
check("empty group: its heading is still shown", len(headings2) == 1 and "21.03.2027 – 25.03.2027" in headings2[0])
check("empty group: the dedicated partner card appears under the heading, with its dates (once - not also above)",
      panel.count(PCARD) == 1 and panel.index("lodging-results-group-title") < panel.index(PCARD)
      and "21.03.2027" in panel.split(PCARD, 1)[1])

with sqlite3.connect(database.DB_PATH) as conn:
    conn.execute("DELETE FROM members WHERE email='qa-lodging-book@example.com'")
    conn.commit()

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
