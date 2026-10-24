"""QA: the partner cards (lodging + car) show a short "קישור שותף" / "Affiliate
link" label linking to the affiliate-disclosure page, instead of the commission
sentence (the business owner, 23.10, via Shlomo). The sentence was Hebrew-only,
so it also showed in Hebrew on the English page (account.html car card).

Same label, class and link as the lodging results' existing affiliate label (#153).
The disclosure page itself (/affiliate-disclosure) is unchanged.

Offline (partner cards stubbed). Run: python3 tools/qa_partner_cards_affiliate_label.py
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


def panel(html, name, next_name):
    start = html.index(f'class="vacation-panel" id="{name}-')
    return html[start:html.index(f'class="vacation-panel" id="{next_name}-', start)]


EMAIL = "qa-partner-affiliate-label@example.com"
with sqlite3.connect(database.DB_PATH) as conn:
    conn.execute("DELETE FROM members WHERE email=?", (EMAIL,))
    member_id = conn.execute(
        "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) VALUES(?,?,?,?,?,?,?)",
        ("QA", EMAIL, generate_password_hash("x"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
    ).lastrowid
    conn.execute("INSERT INTO trip_requests (member_id, request_name, status, answers_json, created_at) VALUES (?,?,?,?,datetime('now'))",
                 (member_id, "QA Partner", "active", json.dumps({"destinations": "LIS", "departure_date": "2027-05-01",
                                                                 "return_date": "2027-05-08", "adults": 2,
                                                                 "_requested_services": ["lodging", "car"]})))
    conn.commit()
with client.session_transaction() as sess:
    sess["member_id"] = member_id

STAY = {"name": "Booking.com", "supplier": "Booking.com", "link": "https://example.com/stay", "dates": "", "guests": ""}
CAR = {"name": "VIP Cars", "supplier": "VIP Cars", "link": "https://example.com/car", "pickup": "LIS", "pickup_when": "", "return_when": ""}
LABEL = {"he": "קישור שותף", "en": "Affiliate link"}
with patch.object(public_site, "_lodging_partner_cards", return_value=[STAY]), patch.object(public_site, "_car_partner_cards", return_value=[CAR]):
    for lang in ("he", "en"):
        html = client.get(f"/account?lang={lang}").get_data(as_text=True)
        for name, nxt in (("lodging", "car"), ("car", "travel")):
            p = panel(html, name, nxt)
            check(f"{lang} {name} partner card: '{LABEL[lang]}' label linking to the disclosure page",
                  f'href="/affiliate-disclosure" target="_blank" rel="noopener">{LABEL[lang]}</a>' in p)
            check(f"{lang} {name} partner card: no commission sentence", "מקבלת עמלה" not in p and "commission" not in p)
        if lang == "en":
            check("en: no Hebrew label on the English page's partner cards", "קישור שותף" not in panel(html, "lodging", "travel"))

src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "account.html"), encoding="utf-8").read()
check("template: the Hebrew-only commission sentence is gone", "אריאלה מקבלת עמלה מהספק" not in src)

with sqlite3.connect(database.DB_PATH) as conn:
    conn.execute("DELETE FROM members WHERE email=?", (EMAIL,))
    conn.commit()

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
