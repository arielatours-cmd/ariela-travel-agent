"""QA for the top-priority bug from Shaked's round-14 QA run (2026-10-14,
qa/reports/2026-10-14-round14.md on the shaked branch): the "you already
have an active vacation" guard in chat_clean() fired on almost every single
test (10 of 14) regardless of what the customer actually asked for next -
"היי, אני רוצה עוד טיסה" (no destination at all), "רוצה לתכנן חופשה חדשה",
even an explicit request for a totally different destination - always
naming the PREVIOUS trip. It also turned the separate "reopen an existing
vacation to add a missing service" flow into an unbreakable loop (A7).
Meanwhile the one case it should have caught - an exact re-description of
the same destination+dates (A6) - slipped through and created a duplicate
vacation + wasted a real scan.

Root cause traced directly in chat_clean(): the guard checked
trip_state.get('combined_search_launched') and, if true, looked up
_find_recent_scanned_vacation using THAT SAME stale trip_state's own
destination_airports/dates - which is circular (it's the very record that
scan itself just created) and has nothing to do with what the CURRENT
message is actually about. Fixed: the stale flag is now only trusted as
"still the same trip" when the new message actually names that trip's own
destination again (via _mentioned_places); any other message - a different
destination, a generic new request, a bare greeting - drops the stale flag
instead of trusting it. The guard is also skipped entirely while an
explicit reopen-existing-vacation flow (reopened_trip_id/reopen_trip_pending)
is in progress.

Run: python3 tools/qa_duplicate_vacation_guard_destination_check.py
"""
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

import ariella_chat_clean as chat
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


def _fake_post_claude(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return "{}"
    return "תשובה לדוגמה מאריאלה."


def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA Duplicate Guard", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def _make_rome_trip(member_id):
    answers = {
        "origin_airports": ["TLV"], "destinations": "FCO",
        "departure_date": "2026-11-10", "return_date": "2026-11-14",
        "adults": 2,
    }
    with sqlite3.connect(DB) as conn:
        cur = conn.execute(
            "INSERT INTO trip_requests (member_id, request_name, created_at, status, answers_json) VALUES(?,?,?,?,?)",
            (member_id, "רומא", datetime.now(timezone.utc).isoformat(), "active", json.dumps(answers, ensure_ascii=False)),
        )
        return cur.lastrowid


member_id = _make_member("qa-dup-guard@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id

STALE_ROME_STATE = {
    "combined_search_launched": True,
    "destination": {"places": ["רומא"], "mode": "specific", "status": "known"},
    "destination_airports": ["FCO"],
    "departure_airport": "TLV",
    "dates": {"departure": "2026-11-10", "return": "2026-11-14", "needs_confirmation": False},
}

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):

    # --- 1. The exact live bug: a bare, destination-less new request after
    #        a scan must NOT see the old trip's duplicate-vacation message ---
    r1 = client.post("/api/ariella/chat-clean", json={
        "message": "היי, אני רוצה עוד טיסה", "history": [], "trip_state": dict(STALE_ROME_STATE),
    })
    data1 = r1.get_json()
    check("bare 'I want another flight' (no destination) does not get the stale duplicate message",
          "כבר יש לך חופשה פעילה" not in str(data1.get("reply") or ""))

    # --- 2. An explicit request for a totally different destination must
    #        also not see the old (Rome) trip's duplicate message ---
    r2 = client.post("/api/ariella/chat-clean", json={
        "message": "רוצה לתכנן חופשה חדשה לברצלונה", "history": [], "trip_state": dict(STALE_ROME_STATE),
    })
    data2 = r2.get_json()
    check("an explicit different-destination request does not get the stale Rome duplicate message",
          "כבר יש לך חופשה פעילה" not in str(data2.get("reply") or ""))

    # --- 3. Genuinely re-naming the SAME destination the stale state was
    #        about, with a real matching DB record, DOES still trigger the
    #        intended duplicate-vacation message (the guard's real job) ---
    _make_rome_trip(member_id)
    r3 = client.post("/api/ariella/chat-clean", json={
        "message": "אני רוצה שוב טיסה לרומא", "history": [], "trip_state": dict(STALE_ROME_STATE),
    })
    data3 = r3.get_json()
    check("re-naming the SAME already-scanned destination still triggers the duplicate-vacation message",
          "כבר יש לך חופשה פעילה" in str(data3.get("reply") or ""))
    check("the duplicate message names the right destination (רומא)",
          "רומא" in str(data3.get("reply") or ""))

    # --- 4. The explicit reopen-existing-vacation flow must never be
    #        blocked by this guard, even with combined_search_launched set ---
    reopen_state = dict(STALE_ROME_STATE)
    reopen_state["reopened_trip_id"] = 999
    r4 = client.post("/api/ariella/chat-clean", json={
        "message": "מלון, חדר אחד, עד 500 ללילה", "history": [], "trip_state": reopen_state,
    })
    data4 = r4.get_json()
    check("an in-progress reopen-existing-vacation flow is never blocked by the duplicate guard",
          "כבר יש לך חופשה פעילה" not in str(data4.get("reply") or ""))

    # --- 5. A pending reopen-choice flow (reopen_trip_pending) is also
    #        exempt from the guard ---
    pending_state = dict(STALE_ROME_STATE)
    pending_state["reopen_trip_pending"] = {"service": "lodging", "options": [{"id": 999, "name": "רומא", "window": ""}]}
    r5 = client.post("/api/ariella/chat-clean", json={
        "message": "רומא", "history": [], "trip_state": pending_state,
    })
    data5 = r5.get_json()
    check("a pending reopen-choice flow is also exempt from the duplicate guard",
          "כבר יש לך חופשה פעילה" not in str(data5.get("reply") or ""))

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM trip_requests WHERE member_id=?", (member_id,))
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DUPLICATE-VACATION-GUARD-DESTINATION-CHECK TESTS PASSED")
