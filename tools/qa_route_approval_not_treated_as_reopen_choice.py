"""QA for a bug Shaked found in round-14's second pass (qa-s91, Sicily,
2026-10-15): with two prior vacations on the account that still had an
open trip_planning gap (Italy, Paris), the customer approved a freshly-
proposed day-by-day Sicily route ("מתאים") and instead of closing
trip_planning, Ariella asked "לאיזו חופשה להוסיף מסלול ואטרקציות? 1. איטליה
(...) 2. פריז (...) או שזו חופשה חדשה?" - the exact "reopen an existing
vacation to add a missing service" offer, firing on a route APPROVAL for
the CURRENT, already in-progress trip instead.

Root cause traced directly in chat_clean(): the "open_places" reopen-offer
gate only checks whether reopenable candidate vacations exist for the
active service (trip_planning here) - it never checks whether the
customer's message is actually answering something Ariella just asked IN
THIS conversation. An itinerary reply is never a "which vacation did you
mean" moment; it's always about whatever route was just shown. Fixed by
skipping this gate entirely whenever the most recent assistant message
already looks like a day-by-day itinerary (2+ "יום N" markers), letting
the real route-approval handling further down the function resolve it
instead.

Run: python3 tools/qa_route_approval_not_treated_as_reopen_choice.py
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
            ("QA Route Approval", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
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


member_id = _make_member("qa-route-approval@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id
_make_reopenable_trip(member_id, "איטליה", "FCO")
_make_reopenable_trip(member_id, "פריז", "CDG")

route_text = (
    "יום 1, 1.6.2027 (שלישי)\nנחיתה בסיציליה.\n\n"
    "יום 2, 2.6.2027 (רביעי)\nסיור בעיר.\n\n"
    "מתאים לך ככה, או שתרצי לשנות משהו?"
)
history = [
    {"role": "user", "content": "אני רוצה מסלול לסיציליה"},
    {"role": "assistant", "content": route_text},
]
sicily_state = {
    "destination": {"places": ["סיציליה"], "mode": "specific", "status": "known"},
    "active_session": "trip_planning",
    "requested_services": ["trip_planning"],
    "session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "active"},
}

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r = client.post("/api/ariella/chat-clean", json={
        "message": "מתאים", "history": history, "trip_state": dict(sicily_state),
    })
data = r.get_json()
check("approving a just-proposed route does not get asked 'which vacation?'",
      "לאיזו חופשה" not in str(data.get("reply") or ""))
check("the reopen_trip_pending gate is not set on the response's trip_update",
      not bool((data.get("trip_update") or {}).get("reopen_trip_pending")))

# --- Regression guard: the ORIGINAL use case (no route just proposed, a
#     genuinely open conversation about a destination with reopenable
#     vacations) must still correctly offer to reopen ---
history_no_route = [{"role": "assistant", "content": "איזה כיף! ספרי לי עוד על התוכניות שלך."}]
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r2 = client.post("/api/ariella/chat-clean", json={
        "message": "אטרקציות באיטליה בבקשה", "history": history_no_route, "trip_state": dict(sicily_state),
    })
data2 = r2.get_json()
check("without a just-proposed route, the reopen offer still works normally",
      "לאיזו חופשה" in str(data2.get("reply") or "") or bool((data2.get("trip_update") or {}).get("reopen_trip_pending")))

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM trip_requests WHERE member_id=?", (member_id,))
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL ROUTE-APPROVAL-NOT-TREATED-AS-REOPEN-CHOICE TESTS PASSED")
