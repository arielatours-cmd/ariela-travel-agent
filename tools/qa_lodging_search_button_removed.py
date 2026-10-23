"""QA: the "search real lodging" button is removed from the lodging tab (the
business owner, 23.10, via Shlomo - a Cyprus LCA/PFO trip with no lodging
results showed the button + "מציג תוצאות אמיתיות (כולל מבוקינג...)").

- The button and its text are gone, in Hebrew and English.
- No results and no partner card -> the heading + a plain empty-state line,
  like the car tab (no empty frame).
- A partner card (Booking.com/CJ) still shows when there are no results,
  with no empty-state line under it.
- The "להזמנה" / "Book" buttons of existing lodging results are untouched.

Offline (account page rendered with stored answers). Run:
python3 tools/qa_lodging_search_button_removed.py
"""
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import database  # noqa: E402
database.init_db()

import app as app_module  # noqa: E402
import public_site  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

client = app_module.app.test_client()
FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


def page(email, answers, lang="he"):
    with sqlite3.connect(database.DB_PATH) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        member_id = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA", email, generate_password_hash("x"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        ).lastrowid
        conn.execute("INSERT INTO trip_requests (member_id, request_name, status, answers_json, created_at) "
                     "VALUES (?,?,?,?,datetime('now'))", (member_id, "QA Lodging Btn", "active", json.dumps(answers, ensure_ascii=False)))
        conn.commit()
    with client.session_transaction() as sess:
        sess["member_id"] = member_id
    return client.get(f"/account?lang={lang}").get_data(as_text=True)


def lodging_panel(html):
    start = html.index('class="vacation-panel" id="lodging-')
    return html[start:html.index('class="vacation-panel" id="car-', start)]


BASE = {"destinations": "LCA,PFO", "departure_date": "2027-05-01", "return_date": "2027-05-08", "adults": 2,
        "lodging_type": "מלון", "_requested_services": ["lodging"]}

src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "account.html"), encoding="utf-8").read()
check("template: no search_lodging form and no button text (he/en)",
      "url_for('site.search_lodging'" not in src and "חיפוש לינה אמיתית" not in src and "Search real lodging" not in src)
check("template: the explanation under the button is gone (he/en)",
      "כולל מבוקינג" not in src and "including Booking.com" not in src)

with patch.object(public_site, "_lodging_partner_cards", return_value=[]):
    he = lodging_panel(page("qa-lodging-btn-he@example.com", dict(BASE)))
    en = lodging_panel(page("qa-lodging-btn-en@example.com", dict(BASE), lang="en"))
check("HE no results, no partner card: no button, a plain empty-state line",
      "<button" not in he and "כאן יוצגו אפשרויות לינה" in he)
check("EN no results, no partner card: no button, a plain empty-state line",
      "<button" not in en and "Lodging options will appear here" in en and "Search real lodging" not in en)

STAY = {"name": "Booking.com", "supplier": "Booking.com", "link": "https://example.com/stay", "dates": "", "guests": ""}
with patch.object(public_site, "_lodging_partner_cards", return_value=[STAY]):
    he = lodging_panel(page("qa-lodging-btn-partner@example.com", dict(BASE)))
check("no results but a partner card: the card shows, no empty-state line under it",
      "lodging-partner-card" in he and "כאן יוצגו אפשרויות לינה" not in he)

offers = [{"name": "Hotel One", "link": "https://www.booking.com/hotel/cy/one.html"}]
with patch.object(public_site, "_lodging_partner_cards", return_value=[]):
    he = lodging_panel(page("qa-lodging-btn-offers@example.com", dict(BASE, lodging_offers=offers)))
    en = lodging_panel(page("qa-lodging-btn-offers-en@example.com", dict(BASE, lodging_offers=offers), lang="en"))
check("existing results: the 'להזמנה ←' button is untouched", "lodging-book-btn" in he and "להזמנה ←" in he)
check("existing results (EN): the 'Book →' button is untouched", "lodging-book-btn" in en and "Book →" in en)
check("existing results: no empty-state line", "כאן יוצגו אפשרויות לינה" not in he)

with sqlite3.connect(database.DB_PATH) as conn:
    conn.execute("DELETE FROM members WHERE email LIKE 'qa-lodging-btn-%'")
    conn.commit()

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
