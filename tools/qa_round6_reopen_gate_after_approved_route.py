"""QA for a SEVERE regression Shaked found in round 6 (qa-s96, 2026-10-16,
on 89675e5) - worse than the round-4 loop bug her earlier report (and
PR #37) already fixed.

Live transcript (Sicily, trip 249): right after the day-by-day route was
approved ("מתאים"), the customer said "כן, גם לינה. מלון..." (yes, also
lodging. hotel...). Ariella replied "להוסיף מסלול ואטרקציות לחופשה לרומא?
(כן = לחופשה הזו, לא = חופשה חדשה)" - the exact reopen-gate question,
offering an unrelated OLD vacation (Rome) instead of continuing Sicily.
The customer answered "לא, אני מדברת על הלינה לסיציליה שאנחנו מתכננות
עכשיו" (no, I'm talking about the lodging for Sicily we're planning NOW).
_pick_reopen_option read this BACKWARDS - as ACCEPTING Rome instead of
declining it - so destination was silently replaced with Rome, lodging
was declined, and the already-approved Sicily route was lost entirely.

Two root causes, both fixed here:

1. The open_places reopen-gate's "skip if we're mid an in-session
   question" check (added in PR #37) only looked at whether the last
   assistant message WAS one of Ariella's own gap-questions - it never
   checked whether a day-by-day route had ALREADY been approved for the
   current destination earlier in this same conversation. An approved
   route (trip_planning.approved) is unambiguous proof this is deep,
   concrete, already-committed progress - never a vague "destination
   merely mentioned" moment the gate exists for. Fixed by adding that as
   an explicit skip condition.

2. _pick_reopen_option had no deterministic handling for a free-text
   reply that OPENS with "לא" but doesn't exactly match the bare "לא"/"לא
   תודה" strings - it fell through to the model-based interpreter, which
   read it backwards. "לא" opening a reply to a binary "add to X? (yes=
   this one, no=new)" question always means decline, regardless of what
   follows - fixed with a deterministic prefix check before ever
   consulting the model.

Also covers C3 (ski, "תמליצי לי"): the SAME gate's trip_is_empty branch
fires on a misclassified "recommend" request, offers an unrelated old
vacation, and declining it ("לא") used to lose the ski type and traveler
count that were stated in the ORIGINAL message that triggered the offer
(one turn back by the time the customer replies) - fixed by storing that
original message as `trigger_message` on the pending offer and seeding
the fresh state from it too when declining.

Run: python3 tools/qa_round6_reopen_gate_after_approved_route.py
"""
import os
import sys
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
import json

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
    return "תשובה לדוגמה."


def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA Round6 Reopen Gate", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def _make_reopenable_trip(member_id, name, destinations):
    answers = {
        "origin_airports": ["TLV"], "destinations": destinations,
        "departure_date": "2027-04-10", "return_date": "2027-04-17",
        "adults": 2,
    }
    with sqlite3.connect(DB) as conn:
        cur = conn.execute(
            "INSERT INTO trip_requests (member_id, request_name, travel_window, created_at, status, answers_json) VALUES(?,?,?,?,?,?)",
            (member_id, name, "10.4-17.4.2027", datetime.now(timezone.utc).isoformat(), "active", json.dumps(answers, ensure_ascii=False)),
        )
        return cur.lastrowid


member_id = _make_member("qa-round6-reopen-gate@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id
_make_reopenable_trip(member_id, "רומא", "FCO")

# --- 1. The severe Sicily case: a lodging request right after route
#     approval must never reopen the gate at all ---
sicily_state = {
    "destination": {"places": ["סיציליה"], "mode": "specific", "status": "known"},
    "active_session": "trip_planning",
    "requested_services": ["trip_planning"],
    "trip_planning": {"approved": True},
    "session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "active"},
}
history_after_approval = [{"role": "assistant", "content": "המסלול שהצעתי מתאים לכם, או שתרצו לשנות משהו?"}]
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r = client.post("/api/ariella/chat-clean", json={
        "message": "כן, גם לינה. מלון בבקשה", "history": history_after_approval, "trip_state": dict(sicily_state),
    })
data = r.get_json()
update = data.get("trip_update") or {}
check("a lodging request right after route approval does not reopen the gate",
      "לאיזו חופשה" not in str(data.get("reply") or "") and not update.get("reopen_trip_pending"))
check("the Sicily destination survives (never silently replaced with Rome)",
      "סיציליה" in ((update.get("destination") or {}).get("places") or []))

# --- 2. Even if the gate DOES fire (genuinely ambiguous case), a free-text
#     "לא, ..." reply must deterministically decline, never accept ---
options_rome = [{"id": 1, "name": "רומא", "window": "10.4-17.4.2027"}]
choice = chat._pick_reopen_option("לא, אני מדברת על הלינה לסיציליה שאנחנו מתכננות עכשיו", options_rome)
check("'לא, ...' (mentioning the current, different vacation) deterministically declines",
      choice == "new")
check("bare 'לא' still declines as before", chat._pick_reopen_option("לא", options_rome) == "new")
check("'לא תודה' still declines as before", chat._pick_reopen_option("לא תודה", options_rome) == "new")
check("a word merely starting with the letters לא ('לאט') is not falsely treated as a decline",
      chat._pick_reopen_option("לאט לאט", options_rome) != "new")

# --- 3. C3-style: declining a trip_is_empty-triggered offer must recover
#     the ski type and travelers stated in the ORIGINAL triggering message ---
pending_with_trigger = {
    "reopen_trip_pending": {
        "service": "trip_planning", "services": ["trip_planning"],
        "options": [{"id": 999999, "name": "רומא", "window": "10.4-17.4.2027"}],
        "trigger_message": "תמליצי לי, חופשת סקי, אני ובעלי",
    },
}
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r2 = client.post("/api/ariella/chat-clean", json={
        "message": "לא", "history": [], "trip_state": dict(pending_with_trigger),
    })
data2 = r2.get_json()
update2 = data2.get("trip_update") or {}
check("declining a trip_is_empty reopen offer recovers the ski type from the original trigger message",
      update2.get("trip_type") == "ski")
check("declining also recovers the traveler count from the original trigger message",
      (update2.get("travelers") or {}).get("adults") == 2)

# --- Regression guard: the genuine original use case (New York attractions
#     mentioned with NO prior approved route) must still correctly offer
#     to reopen ---
history_no_route = [{"role": "assistant", "content": "איזה כיף! ספרי לי עוד על התוכניות שלך."}]
rome_state_no_approval = {
    "destination": {"places": ["רומא"], "mode": "specific", "status": "known"},
    "active_session": "trip_planning",
    "requested_services": ["trip_planning"],
    "session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "active"},
}
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r3 = client.post("/api/ariella/chat-clean", json={
        "message": "אטרקציות ברומא בבקשה", "history": history_no_route, "trip_state": dict(rome_state_no_approval),
    })
data3 = r3.get_json()
check("without an approved route, the reopen offer still works normally (no false exemption)",
      "לאיזו חופשה" in str(data3.get("reply") or "") or bool((data3.get("trip_update") or {}).get("reopen_trip_pending")))

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM trip_requests WHERE member_id=?", (member_id,))
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL ROUND6-REOPEN-GATE-AFTER-APPROVED-ROUTE TESTS PASSED")
