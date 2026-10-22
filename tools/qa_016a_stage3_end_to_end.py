"""QA for task 016a Stage 3: the full end-to-end pipeline through the real
Flask routes with ROUTE_BUILD_ASYNC on - a route-build turn gets queued via
/api/ariella/chat-clean, and polling /api/ariella/route-status/<job_id>
(the new Stage 3 endpoint) correctly tracks it from 'building' through to
the real, fully-processed route reply, exactly as the in-chat indicator in
trip_form.html would see it.

Run: python3 tools/qa_016a_stage3_end_to_end.py
"""
import json
import os
import sys
import sqlite3
import time
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ["ROUTE_BUILD_ASYNC"] = "1"

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


def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA 016a Stage3 E2E", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def _fake_post_claude_route(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "route_ack":
        return "אני בונה לכם את המסלול עכשיו, רגע קטן!"
    if source == "state_extractor":
        return json.dumps({"trip_update": {}})
    return "יום 1: נחיתה ברומא. יום 2: סיור בעיר העתיקה."


ROUTE_READY_TRIP_STATE = {
    "destination": {"places": ["רומא"], "mode": "specific", "status": "known"},
    "dates": {"departure": "2027-06-01", "return": "2027-06-08"},
    "travelers": {"adults": 2, "children": 0},
    "requested_services": ["flights", "trip_planning"],
    "service_decisions": {"flights": {"wanted": True}, "trip_planning": {"wanted": True}},
    "session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "active"},
    "active_session": "trip_planning",
    "trip_planning": {"interested": True, "details": {"style": "תרבות", "pace": "relaxed"}},
}

member = _make_member("qa-016a-stage3-e2e@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_route):
    resp = client.post("/api/ariella/chat-clean", json={
        "message": "תציעי מסלול בבקשה",
        "history": [],
        "trip_state": ROUTE_READY_TRIP_STATE,
    })
    data = resp.get_json()
    job_id = data.get("route_build_job_id")
    check("chat-clean dispatches a background job and returns the quick ack", isinstance(job_id, int))

    # Poll the way the frontend's pollRouteBuild() does - immediately, before
    # the background thread has necessarily finished.
    poll_resp = client.get(f"/api/ariella/route-status/{job_id}")
    poll_data = poll_resp.get_json()
    check("first poll (likely still building or just finished) is a valid status", poll_data.get("status") in ("building", "ready"))

    thread = chat._route_build_threads.get(member)
    if thread:
        thread.join(timeout=20)

final_poll = client.get(f"/api/ariella/route-status/{job_id}")
final_data = final_poll.get_json()
check("job eventually reaches status=ready via polling", final_data.get("status") == "ready")
check("stages.plan=complete once ready", (final_data.get("stages") or {}).get("plan") == "complete")
check("the real, fully-processed route reply is what the client would show", "יום 1" in (final_data.get("reply") or ""))
check("a real trip_update is attached for the client to persist", isinstance(final_data.get("trip_update"), dict))

print()
if FAILED:
    print(f"FAILED ({len(FAILED)}): {FAILED}")
    sys.exit(1)
print("ALL 016A-STAGE3-END-TO-END TESTS PASSED")
