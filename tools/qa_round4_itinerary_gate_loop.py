"""QA for the round-4 bug Shaked flagged as the top blocker (A5/A8/C3/C2,
2026-10-16): answering Ariella's own in-session trip_planning questions
("אתם מעדיפים קצב רגוע או פעיל?", "ספרו לי מה אתם אוהבים לעשות בחופשה",
"המסלול שהצעתי מתאים לכם, או שתרצו לשנות משהו?") with normal replies like
"ים וטבע, קצב רגוע", "תמליצי" or even "מאשרת" got reinterpreted as answers
to the "לאיזו חופשה להוסיף מסלול ואטרקציות?" reopen-offer instead, because
that gate only skipped itself for the single turn right after a full
day-by-day route was proposed (2+ "יום N" markers) - every other in-session
question was unprotected and kept re-firing the gate every turn, with no
way out once _pick_reopen_option failed to parse the real answer as a
vacation choice. Fixed in two parts: (1) skip the gate whenever the last
assistant message is one of Ariella's own in-session detail/approval
questions (_GAP_QUESTION_TEXT), not just a proposed route; (2) a retry-cap
safety net so that even if the gate does fire, a second unparseable answer
defaults to "new" instead of asking "רק כדי לוודא" forever.

Run: python3 tools/qa_round4_itinerary_gate_loop.py
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
            ("QA Round4 Gate Loop", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
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


member_id = _make_member("qa-round4-gate-loop@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id
_make_reopenable_trip(member_id, "קרואטיה", "DBV")

base_state = {
    "destination": {"places": ["איטליה"], "mode": "specific", "status": "known"},
    "active_session": "trip_planning",
    "requested_services": ["trip_planning"],
    "session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "active"},
}

# --- A5/A8-style: answering the pace question must not trigger the gate ---
history_pace = [{"role": "assistant", "content": "אתם מעדיפים קצב רגוע או פעיל?"}]
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r = client.post("/api/ariella/chat-clean", json={
        "message": "ים וטבע, קצב רגוע", "history": history_pace, "trip_state": dict(base_state),
    })
data = r.get_json()
check("answering the pace question is not treated as a reopen choice",
      "לאיזו חופשה" not in str(data.get("reply") or ""))
check("pace answer: reopen_trip_pending not set on trip_update",
      not bool((data.get("trip_update") or {}).get("reopen_trip_pending")))

# --- style question answered with "תמליצי" (delegating the choice) ---
history_style = [{"role": "assistant", "content": "ספרו לי מה אתם אוהבים לעשות בחופשה."}]
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r2 = client.post("/api/ariella/chat-clean", json={
        "message": "תמליצי", "history": history_style, "trip_state": dict(base_state),
    })
data2 = r2.get_json()
check("answering the style question with 'תמליצי' is not treated as a reopen choice",
      "לאיזו חופשה" not in str(data2.get("reply") or ""))
check("style answer: reopen_trip_pending not set on trip_update",
      not bool((data2.get("trip_update") or {}).get("reopen_trip_pending")))

# --- C2-style: approving the route must not swallow "מאשרת" even when no
#     day-by-day markers are present in the last assistant message (e.g. the
#     route text itself scrolled out of history / was summarized) ---
history_approve = [{"role": "assistant", "content": "המסלול שהצעתי מתאים לכם, או שתרצו לשנות משהו?"}]
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r3 = client.post("/api/ariella/chat-clean", json={
        "message": "מאשרת", "history": history_approve, "trip_state": dict(base_state),
    })
data3 = r3.get_json()
check("'מאשרת' after the approval question is not treated as a reopen choice",
      "לאיזו חופשה" not in str(data3.get("reply") or ""))
check("approval: reopen_trip_pending not set on trip_update",
      not bool((data3.get("trip_update") or {}).get("reopen_trip_pending")))

# --- Regression guard: the ORIGINAL use case (no in-session question just
#     asked, a genuinely open conversation about a destination with
#     reopenable vacations) must still correctly offer to reopen ---
history_no_question = [{"role": "assistant", "content": "איזה כיף! ספרי לי עוד על התוכניות שלך."}]
croatia_state = dict(base_state, destination={"places": ["קרואטיה"], "mode": "specific", "status": "known"})
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r4 = client.post("/api/ariella/chat-clean", json={
        "message": "אטרקציות בקרואטיה בבקשה", "history": history_no_question, "trip_state": dict(croatia_state),
    })
data4 = r4.get_json()
check("without an in-session question just asked, the reopen offer still works normally",
      "לאיזו חופשה" in str(data4.get("reply") or "") or bool((data4.get("trip_update") or {}).get("reopen_trip_pending")))

# --- Safety net: once the reopen question genuinely IS pending, an answer
#     that fails to parse must not loop forever - first re-ask once, then
#     fall through instead of asking a third time ---
pending_state = dict(base_state)
pending_state["reopen_trip_pending"] = {
    "service": "trip_planning", "services": ["trip_planning"], "keep_state": True,
    "options": [{"id": 999999, "name": "קרואטיה", "window": "10.4-17.4.2027"}],
}
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r5 = client.post("/api/ariella/chat-clean", json={
        "message": "ים וטבע, קצב רגוע", "history": [], "trip_state": dict(pending_state),
    })
data5 = r5.get_json()
check("first unparseable answer re-asks (still pending) rather than giving up immediately",
      bool((data5.get("trip_update") or {}).get("reopen_trip_pending")))

retried_state = data5.get("trip_update") or {}
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r6 = client.post("/api/ariella/chat-clean", json={
        "message": "תמליצי", "history": [], "trip_state": dict(retried_state),
    })
data6 = r6.get_json()
check("second unparseable answer stops the loop (reopen_trip_pending cleared)",
      not bool((data6.get("trip_update") or {}).get("reopen_trip_pending")))

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM trip_requests WHERE member_id=?", (member_id,))
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL ROUND4-ITINERARY-GATE-LOOP TESTS PASSED")
