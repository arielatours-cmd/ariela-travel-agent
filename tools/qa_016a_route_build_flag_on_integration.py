"""QA for task 016a Stage 2 (ROUTE_BUILD_ASYNC): end-to-end integration
through the REAL /api/ariella/chat-clean Flask route (not just unit-level
calls to the detection/dispatch functions) - this is the first QA that
actually exercises the wiring inside _chat_clean_impl with the flag turned
on, proving a real HTTP request for a route-build turn gets the fast ack
and a backgrounded job, while an ordinary trip_planning question (style
still unknown) is answered synchronously exactly like today.

Run: ROUTE_BUILD_ASYNC=1 python3 tools/qa_016a_route_build_flag_on_integration.py
(the script sets the env var itself, so a bare `python3 ...` also works)
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
            ("QA 016a Flag-On Integration", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def _fake_post_claude_route(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "route_ack":
        return "אני בונה לכם את המסלול עכשיו, רגע קטן!"
    if source == "state_extractor":
        return json.dumps({"trip_update": {}})
    return "יום 1: נחיתה ברומא. יום 2: סיור בעיר העתיקה."


def _fake_post_claude_question(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "route_ack":
        # Should never be reached for a non-route turn - fail loudly if it is.
        raise AssertionError("route_ack should not be called for an ordinary clarifying-question turn")
    if source == "state_extractor":
        return json.dumps({"trip_update": {}})
    return "ספרו לי מה אתם אוהבים לעשות בחופשה?"


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

STYLE_PENDING_TRIP_STATE = {
    "destination": {"places": ["רומא"], "mode": "specific", "status": "known"},
    "dates": {"departure": "2027-06-01", "return": "2027-06-08"},
    "travelers": {"adults": 2, "children": 0},
    "requested_services": ["flights", "trip_planning"],
    "service_decisions": {"flights": {"wanted": True}, "trip_planning": {"wanted": True}},
    "session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "active"},
    "active_session": "trip_planning",
    "trip_planning": {"interested": True, "details": {}},
}

# --- 1. A real route-build turn: fast ack now, real job dispatched in the background ---
member_a = _make_member("qa-016a-flag-on-a@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_a

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_route):
    started = time.time()
    resp = client.post("/api/ariella/chat-clean", json={
        "message": "תציעי מסלול בבקשה",
        "history": [],
        "trip_state": ROUTE_READY_TRIP_STATE,
    })
    elapsed = time.time() - started
    data = resp.get_json()
    check("HTTP 200 on the route-build turn", resp.status_code == 200)
    check("a job id is returned", isinstance(data.get("route_build_job_id"), int))
    check("the reply is the quick ack sentence, not the real route", data.get("reply") == "אני בונה לכם את המסלול עכשיו, רגע קטן!")
    check("the ack response returns fast (well under the website's normal budget)", elapsed < 10)

    job_id = data["route_build_job_id"]
    thread = chat._route_build_threads.get(member_a)
    if thread:
        thread.join(timeout=20)

job = database.get_route_job(job_id)
check("the background job reaches status=ready", job is not None and job["status"] == "ready")
check("the background job's real reply is the actual route text", job is not None and "יום 1" in (job["result_reply"] or ""))

# --- 2. An ordinary clarifying-question turn (style/pace unknown): stays synchronous, no job ---
member_b = _make_member("qa-016a-flag-on-b@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_b

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_question):
    resp2 = client.post("/api/ariella/chat-clean", json={
        "message": "אנחנו שניים",
        "history": [],
        "trip_state": STYLE_PENDING_TRIP_STATE,
    })
    data2 = resp2.get_json()

check("HTTP 200 on the ordinary question turn", resp2.status_code == 200)
check("no job id on an ordinary synchronous turn", data2.get("route_build_job_id") is None)
check("the reply is the real synchronous reply, not an ack", data2.get("reply") == "ספרו לי מה אתם אוהבים לעשות בחופשה?")
check("no background job was ever created for this member", database.open_route_job_for_member(member_b) is None)

print()
if FAILED:
    print(f"FAILED ({len(FAILED)}): {FAILED}")
    sys.exit(1)
print("ALL 016A-ROUTE-BUILD-FLAG-ON-INTEGRATION TESTS PASSED")
