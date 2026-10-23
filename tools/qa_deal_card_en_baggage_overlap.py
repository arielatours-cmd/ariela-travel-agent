"""QA for the English (lang=en) deal-card mobile overlap (23.10, business
owner's screenshot, relayed by Shlomo): on mobile (<=760px), the baggage
list is narrowed to a fixed 48% column (static/mobile-deal-card-fixes.css,
.baggage-terms-flex ul) so the consumer-protection/change-cancel terms can
sit beside it. That 48% width was sized for Hebrew's short "יש לבדוק" -
the English "Check with provider" kept the desktop .bag-status-price rule's
white-space:nowrap in that same narrow column too, so it overflowed past
the column's edge and visually overlapped the terms block next to it.
Confirmed visually with Playwright screenshots at 390px width before and
after this fix (not checked into the repo - the screenshots themselves,
not this test, were the verification step).

Fixed: static/mobile-deal-card-fixes.css adds a mobile-scoped override,
white-space:normal on .bag-status-price, so the English phrase wraps onto
a second line instead of overflowing. Desktop (outside the 760px media
query) is untouched - verified unchanged by the same screenshots.

Run: python3 tools/qa_deal_card_en_baggage_overlap.py
"""
import os
import re
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
import json

DB = database.DB_PATH
client = app_module.app.test_client()

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


mobile_css = open(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "mobile-deal-card-fixes.css"),
    encoding="utf-8",
).read()

m = re.search(r"@media \(max-width:760px\)\{(.*)\n\}", mobile_css, re.S)
check("sanity: the mobile (<=760px) deal-card media block is present", m is not None)
mobile_block = m.group(1) if m else ""

check("FIX: the mobile block overrides .bag-status-price to white-space:normal "
      "(lets the English phrase wrap instead of overflowing the narrow baggage column)",
      bool(re.search(r"\.bag-status-price\{[^}]*white-space:normal!important", mobile_block)))
check("the narrow 48% baggage column (the actual overflow boundary) is still in place unchanged",
      ".baggage-terms-flex ul{flex:0 0 48%!important" in mobile_block)
site_css = open(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "site.css"),
    encoding="utf-8",
).read()
check("the desktop (non-mobile) .bag-status-price rule in site.css still keeps nowrap - desktop is untouched by this fix",
      ".bag-status-price{display:inline-flex;align-items:center;gap:5px;white-space:nowrap}" in site_css)

base_html = open(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "base.html"),
    encoding="utf-8",
).read()
check("the stylesheet link's cache-busting version was bumped so browsers pick up the fix",
      "mobile-deal-card-fixes.css') }}?v=20261023-card-align" in base_html)


def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA Deal Card Overlap", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


member_id = _make_member("qa-deal-card-overlap@example.com")
with sqlite3.connect(DB) as conn:
    cur = conn.execute(
        "INSERT INTO trip_requests (member_id, request_name, status, answers_json, created_at) VALUES (?,?,?,?,datetime('now'))",
        (member_id, "QA Deal Card Overlap Trip", "active",
         json.dumps({"destinations": "LIS", "departure_date": "2027-04-01", "return_date": "2027-04-08", "adults": 2}, ensure_ascii=False)),
    )
    trip_id = cur.lastrowid
    conn.commit()

BAGGAGE_UNKNOWN = {"personal_item": {"included": True}, "carry_on_8kg": {}, "checked_bag_23kg": {}}
with sqlite3.connect(DB) as conn:
    run = conn.execute("INSERT INTO scan_runs (started_at, status, searches_planned) VALUES (datetime('now'),'done',1)").lastrowid
    flight = {"departure_time": "2027-04-01 19:00", "arrival_time": "2027-04-01 23:00",
              "return_departure_time": "2027-04-08 14:00", "return_arrival_time": "2027-04-08 18:00",
              "stops": 0, "baggage": BAGGAGE_UNKNOWN}
    oid = conn.execute(
        """INSERT INTO offers (scan_run_id, observed_at, route, departure_code, arrival_code, outbound_date, return_date,
        price_ils, score, score_label, departure_time, arrival_time, payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (run, datetime.now(timezone.utc).isoformat(), "TLV-LIS", "TLV", "LIS", "2027-04-01", "2027-04-08", 1234, 70, "good",
         "2027-04-01 19:00", "2027-04-01 23:00", json.dumps({"destination_name": "ליסבון", "flight": flight}, ensure_ascii=False)),
    ).lastrowid
    conn.execute("UPDATE trip_requests SET answers_json=? WHERE id=?",
                 (json.dumps({"destinations": "LIS", "departure_date": "2027-04-01", "return_date": "2027-04-08",
                              "adults": 2, "pinned_offer_ids": [oid]}, ensure_ascii=False), trip_id))
    conn.commit()

with client.session_transaction() as sess:
    sess["member_id"] = member_id

resp_en = client.get("/account?lang=en")
body_en = resp_en.get_data(as_text=True)
check("a real /account?lang=en render with an 'unknown' baggage item still shows 'Check with provider' "
      "(the exact text that overflowed in the business owner's screenshot)",
      resp_en.status_code == 200 and "Check with provider" in body_en)

resp_he = client.get("/account?lang=he")
body_he = resp_he.get_data(as_text=True)
check("REGRESSION GUARD: the same unknown baggage item still shows 'יש לבדוק' in Hebrew",
      resp_he.status_code == 200 and "יש לבדוק" in body_he)

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE email='qa-deal-card-overlap@example.com'")
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DEAL-CARD-EN-BAGGAGE-OVERLAP TESTS PASSED")
