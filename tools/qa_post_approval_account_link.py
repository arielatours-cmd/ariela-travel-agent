"""QA for a fix relayed by Shlomo (business owner's instruction, 17.10.2026):
after the customer approves a search (types "מאשר"/"מאשרת"), the handoff
link/redirect must point to the vacation card on /account (specifically
/account#vacation-<trip_id>, matching templates/account.html's real
id="vacation-{{ trip.id }}" anchor), not to the separate /trip/<id>/waiting
live-progress page. Previously only change_requires_payment (an unrelated,
pre-existing case) used an account_url; every other handoff case
(ariella_start_flight_search's "queued" success path, the duplicate-active-
trip shortcut, and the post-flight-continuation return visit) sent the
customer to /trip/<id>/waiting instead - both from the server's own
"waiting_url" response field and from two separate hardcoded client-side
paths (templates/trip_form.html and the global floating-widget script,
static/ariella-conversation-flow-20260914.js).

Fixed by renaming/repointing every one of those to account_url built the
same way change_requires_payment already did: url_for("site.account") +
f"#vacation-{trip_id}". whatsapp_bridge.py reads the SAME
/api/ariella/start-flight-search response and was updated to match (it
would otherwise have silently stopped sending any link at all, since it
gated on the now-removed "waiting_url" key).

No new code was needed for the "next=/account on login" half of the
request: login_required already redirects an unauthenticated visit to
url_for("site.login", next=request.path), and login() already redirects
to request.args.get("next") after a successful password check - this was
already the general, working pattern used by every @login_required view,
confirmed below rather than assumed.

/trip/<id>/waiting itself is untouched (still a real route, still used by
trip_waiting.html for live in-progress status) - only what customers are
auto-sent to right after approval changed.

Run: python3 tools/qa_post_approval_account_link.py
"""
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

import public_site
from werkzeug.security import generate_password_hash

DB = database.DB_PATH

import app as app_module
client = app_module.app.test_client()

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# === Source-level regression guard: the stale "waiting_url" key must not
#     silently creep back into any of the handoff paths this fix touched ===

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Matches a dict-key/JSON lookup ("waiting_url"/'waiting_url') or a JS
# property access (.waiting_url) - not whatsapp_bridge.py's own _waiting_link
# helper, whose "waiting_url" is just a generic parameter name and is fine
# to keep (it still builds an absolute link from whatever path it's given).
_STALE_KEY_RE = re.compile(r"[\"']waiting_url[\"']|\.waiting_url\b")
for path in ("public_site.py", "whatsapp_bridge.py", "templates/trip_form.html",
             "static/ariella-conversation-flow-20260914.js"):
    text = open(os.path.join(ROOT, path), encoding="utf-8").read()
    check(f"{path}: no remaining 'waiting_url' dict-key/property lookup",
          not _STALE_KEY_RE.search(text))
check("templates/trip_form.html no longer hardcodes a /trip/<id>/waiting redirect",
      "/waiting'" not in open(os.path.join(ROOT, "templates/trip_form.html"), encoding="utf-8").read())
check("the floating-widget script no longer hardcodes a /trip/<id>/waiting redirect",
      "/waiting'" not in open(os.path.join(ROOT, "static/ariella-conversation-flow-20260914.js"), encoding="utf-8").read())


# === End-to-end: the duplicate-active-trip handoff (the simplest of the
#     three server call sites to set up for real) returns account_url, in
#     the exact #vacation-<id> shape the vacation card actually anchors on ===

def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA Post-Approval Link", email, generate_password_hash("Test1234!"),
             datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def _make_active_trip(member_id, origin, destinations, dep, ret):
    answers = {
        "origin_airports": [origin], "destinations": destinations,
        "date_mode": "exact", "departure_date": dep, "return_date": ret,
    }
    with sqlite3.connect(DB) as conn:
        cur = conn.execute(
            "INSERT INTO trip_requests (member_id, request_name, created_at, status, answers_json) VALUES(?,?,?,?,?)",
            (member_id, "קפריסין", datetime.now(timezone.utc).isoformat(), "active", json.dumps(answers, ensure_ascii=False)),
        )
        return cur.lastrowid


member_id = _make_member("qa-post-approval-link@example.com")
existing_trip_id = _make_active_trip(member_id, "TLV", "LCA", "2027-06-10", "2027-06-20")

with client.session_transaction() as sess:
    sess["member_id"] = member_id

dup_trip_state = {
    "search_confirmed": True,
    "requested_services": ["flights"],
    "destination": {"places": ["קפריסין"], "mode": "specific"},
    "destination_airports": ["LCA"],
    "departure_airport": "TLV",
    "dates": {"departure": "2027-06-10", "return": "2027-06-20"},
    "travelers": {"adults": 2},
}
r = client.post("/api/ariella/start-flight-search", json={"trip_state": dup_trip_state, "history": []})
data = r.get_json() or {}

check("duplicate-active-trip handoff: status is duplicate_active_trip (the scenario this test sets up)",
      data.get("status") == "duplicate_active_trip")
check("duplicate-active-trip handoff: response carries account_url, not waiting_url",
      "account_url" in data and "waiting_url" not in data)
check("duplicate-active-trip handoff: account_url targets the vacation card by its real anchor id "
      "(templates/account.html's id=\"vacation-{{ trip.id }}\")",
      data.get("account_url") == f"/account#vacation-{existing_trip_id}")


# === The login "next" redirect this link relies on - confirmed working
#     for /account specifically, not assumed from the general mechanism ===

client.post("/logout")
r_account = client.get("/account", follow_redirects=False)
check("an unauthenticated visit to /account is redirected to login with next=/account",
      r_account.status_code in (301, 302)
      and re.search(r"/login\?next=(?:%2Faccount\b|/account\b)", r_account.headers.get("Location", "")) is not None)

login_resp = client.post(
    r_account.headers["Location"],
    data={"email": "qa-post-approval-link@example.com", "password": "Test1234!"},
    follow_redirects=False,
)
check("logging in via that next=/account link redirects straight to /account",
      login_resp.status_code in (301, 302) and login_resp.headers.get("Location", "").rstrip("/").endswith("/account"))


with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM trip_requests WHERE member_id=?", (member_id,))
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL POST-APPROVAL-ACCOUNT-LINK TESTS PASSED")
