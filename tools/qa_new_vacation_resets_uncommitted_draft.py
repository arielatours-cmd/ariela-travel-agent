"""QA for B2 (Shaked, qa-s97, round 7, focused conversation-flow pass,
2026-10-16): an explicit "new and separate vacation" statement did NOT
reset anything when the OLD trip was still just an open, never-approved
draft - only a committed/launched one.

Live transcript: mid-conversation about a Rome flight (not yet approved -
budget 1200, carry-on-only baggage, direct-flight preference already
given), the customer said "נסיעת עסקים חדשה ונפרדת לאמסטרדם, 1-5 במרץ, 2
נוסעים" (a new and separate BUSINESS trip to Amsterdam...). trip_state_
reset stayed False, and Rome's budget (1200), baggage (carry_on_only) and
direct-flight preference leaked straight into the Amsterdam request, with
flights silently marked "complete" before ever asking about any of them
for the new trip.

Root cause: the hard "new/different vacation" reset (new_vacation_language)
additionally required old_trip_committed (trip_state.search_confirmed or
post_flight_continuation) before firing - so an unambiguous, explicit
"new and separate" statement (matched _NEW_AND_SEPARATE_RE here, and also
a trip_type mismatch: business vs the Rome draft's own) was still ignored
entirely whenever the OLD trip hadn't been approved/launched yet. The
message then fell through to the ordinary extractor merge, which (per its
own "never erase a value not mentioned again" rule) correctly preserves
facts across turns for the SAME trip - but is exactly wrong once the
customer has explicitly declared a different, separate vacation.

Fixed: replaced old_trip_committed with a check for whether trip_state
already has a real destination set (old_trip_has_destination) - the
customer's intent to start fresh matters the same whether the old trip
was ever approved or not; what actually matters is whether there's a real
old destination's preferences to protect against leaking. Deliberately
NOT _has_vacation_progress (a broader helper used for the idle-timeout
reset): by the time this check runs, trip_state can already carry fields
THIS SAME message derived moments earlier in the same turn (requested-
service classification sets active_session/session_status before this
line runs) - _has_vacation_progress read those as "old progress" even on
an originally blank trip_state, which broke the existing reset-gate test
(tools/qa_reset_gate_preserves_trip_type_and_specific_resort.py) by firing
the hard reset instead of the gentler generic restart-confirmation gate
that scenario needs.

Run: python3 tools/qa_new_vacation_resets_uncommitted_draft.py
"""
import os
import sys
import json
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

import ariella_chat_clean as chat
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


def _fake_post_claude(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({"trip_update": {
            "destination": {"places": ["אמסטרדם"], "mode": "specific", "status": "known"},
            "trip_type": "business",
            "dates": {"departure": "2027-03-01", "return": "2027-03-05", "needs_confirmation": False},
            "travelers": {"adults": 2, "children": 0, "child_ages": [], "child_genders": []},
        }})
    return "בשמחה, נסיעת עסקים חדשה לאמסטרדם."


def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA Uncommitted Draft Reset", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


member_id = _make_member("qa-uncommitted-draft-reset@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id

# A Rome flight draft - NOT approved, NOT launched - mid-conversation.
rome_draft_state = {
    "destination": {"places": ["רומא"], "mode": "specific", "status": "known"},
    "trip_type": "standard",
    "budget_per_person": {"amount": 1200, "currency": "ILS", "status": "known"},
    "flight": {"connection_preference": "direct", "baggage": ["carry_on_only"]},
    "active_session": "flights",
    "session_status": {"flights": "active", "lodging": "pending", "car": "pending", "trip_planning": "pending"},
}

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r = client.post("/api/ariella/chat-clean", json={
        "message": "נסיעת עסקים חדשה ונפרדת לאמסטרדם, 1 עד 5 במרץ, 2 נוסעים", "history": [],
        "trip_state": dict(rome_draft_state),
    })
data = r.get_json()
update = data.get("trip_update") or {}

check("the reset fires for an explicit new-and-separate statement even on an UNCOMMITTED draft",
      data.get("trip_state_reset") is True)
check("the new destination (Amsterdam) is set",
      "אמסטרדם" in ((update.get("destination") or {}).get("places") or []))
check("the old trip's budget (1200) does not leak into the new vacation",
      update.get("budget_per_person") is None or not (update.get("budget_per_person") or {}).get("amount"))
check("the old trip's baggage/connection preference does not leak into the new vacation",
      not update.get("flight"))
check("trip_type reflects the new statement (business), not the old draft's (standard)",
      update.get("trip_type") != "standard")
check("session_status is reset to pending, not inherited from the old draft",
      all(v == "pending" for v in (update.get("session_status") or {}).values()))

# --- Regression guard: a committed/launched old trip (the original,
#     already-working case) must still reset correctly too ---
budapest_committed_state = {
    "destination": {"places": ["בודפשט"], "mode": "specific", "status": "known"},
    "trip_type": "standard",
    "search_confirmed": True,
    "post_flight_continuation": True,
    "budget_per_person": {"amount": 2000, "currency": "ILS", "status": "known"},
    "session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
}
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r2 = client.post("/api/ariella/chat-clean", json={
        "message": "נסיעת עסקים חדשה ונפרדת לאמסטרדם, 1 עד 5 במרץ, 2 נוסעים", "history": [],
        "trip_state": dict(budapest_committed_state),
    })
data2 = r2.get_json()
update2 = data2.get("trip_update") or {}
check("regression guard: a committed old trip still resets correctly",
      data2.get("trip_state_reset") is True and "אמסטרדם" in ((update2.get("destination") or {}).get("places") or []))
check("regression guard: the old committed trip's budget does not leak either",
      update2.get("budget_per_person") is None or not (update2.get("budget_per_person") or {}).get("amount"))

# --- Regression guard: the generic restart-confirmation gate (for a truly
#     blank trip_state, no old destination at all) must still fire its own
#     separate flow, not this hard reset. A fresh member/session - the
#     earlier cases above already left a saved conversation for member_id,
#     and an empty trip_state in the request falls back to it otherwise. ---
member_id_blank = _make_member("qa-uncommitted-draft-reset-blank@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id_blank
with patch.object(chat, "_post_claude", side_effect=lambda *a, **kw: ("{}" if kw.get("source") == "state_extractor" else "תשובה לדוגמה.")):
    r3 = client.post("/api/ariella/chat-clean", json={
        "message": "אני רוצה לפתוח חופשה חדשה ונפרדת: חופשת סקי בזאלבאך שבאוסטריה, עם טיסה ולינה",
        "history": [], "trip_state": {},
    })
data3 = r3.get_json()
update3 = data3.get("trip_update") or {}
check("regression guard: a blank trip_state still gets the gentler restart-confirmation gate, not this hard reset",
      bool(update3.get("reset_pending")) and data3.get("trip_state_reset") is not True)

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE id IN (?, ?)", (member_id, member_id_blank))
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL NEW-VACATION-RESETS-UNCOMMITTED-DRAFT TESTS PASSED")
