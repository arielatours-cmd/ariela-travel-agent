"""QA for task 016a Stage 1 (ROUTE_BUILD_ASYNC): the route_jobs DB layer
and the background-thread dispatch core (_queue_route_build /
_run_route_build_job in ariella_chat_clean.py).

Nothing calls _queue_route_build yet - the detection logic that decides
WHEN a turn should go to the background is Stage 2, not built here. This
only proves the dispatch core itself is correct in isolation: a queued job
runs _run_chat_turn_engine (the exact same turn-processing code extracted
from the old _chat_clean_impl) in its own thread, with no Flask
request/session context, and records a real result (or a real failure) on
the route_jobs row - plus the one-job-per-member dedup and the thread's own
150s budget being separate from the website's normal 90s per-request one.

Run: python3 tools/qa_016a_route_build_dispatch_core.py
"""
import json
import os
import sys
import sqlite3
import threading
import time
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

import ariella_chat_clean as chat
import app as app_module  # noqa: F401 - imported so chat's lazy `from app import app` resolves
from werkzeug.security import generate_password_hash

DB = database.DB_PATH

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
            ("QA 016a Dispatch Core", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def _fake_post_claude_ok(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({"trip_update": {}})
    return "המסלול מוכן! יום 1: נחיתה. יום 2: סיור."


def _fake_engine_crash(member_id, message, history, trip_state, channel=None):
    # Every _post_claude call site already has its own graceful fallback
    # (see _claude_call_timeout's docstring), so a single failed model call
    # alone never crashes _run_chat_turn_engine - it still returns a reply.
    # To test _run_route_build_job's OWN exception handling in isolation,
    # this breaks the engine itself, not just one of its model calls.
    raise RuntimeError("simulated engine crash")


BASE_TRIP_STATE = {
    "destination": {"places": ["רומא"], "mode": "specific", "status": "known"},
    "dates": {"departure": "2027-06-01", "return": "2027-06-08"},
    "travelers": {"adults": 2, "children": 0},
    "active_session": "trip_planning",
}

# --- 1. Happy path: job runs to completion in the background and records a real result ---
member_a = _make_member("qa-016a-dispatch-a@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_ok):
    job_id = chat._queue_route_build(member_a, "website", "תציעי מסלול", [], dict(BASE_TRIP_STATE))
    check("queueing a job returns an id immediately", isinstance(job_id, int))
    thread = chat._route_build_threads.get(member_a)
    if thread:
        thread.join(timeout=20)

job = database.get_route_job(job_id)
check("job reaches status=ready", job is not None and job["status"] == "ready")
check("job carries the real reply text", job is not None and "המסלול" in (job["result_reply"] or ""))
check("job carries a trip_update dict", job is not None and isinstance(job["result_trip_update"], dict))
check("thread entry is cleaned up after finishing", chat._route_build_threads.get(member_a) is None)

# --- 2. Dedup: a second build for the SAME member while one is still running is refused ---
member_b = _make_member("qa-016a-dispatch-b@example.com")
release = threading.Event()


def _slow_post_claude(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({"trip_update": {}})
    release.wait(timeout=10)
    return "מסלול איטי"


with patch.object(chat, "_post_claude", side_effect=_slow_post_claude):
    first_job_id = chat._queue_route_build(member_b, "website", "תציעי מסלול", [], dict(BASE_TRIP_STATE))
    time.sleep(0.3)  # let the worker thread actually start and register itself
    second_job_id = chat._queue_route_build(member_b, "website", "עוד הודעה", [], dict(BASE_TRIP_STATE))
    check("a second queue attempt while one is building returns None", second_job_id is None)
    release.set()
    thread = chat._route_build_threads.get(member_b)
    if thread:
        thread.join(timeout=20)

check("the original (first) job still completes normally", database.get_route_job(first_job_id)["status"] == "ready")

# --- 3. Failure path: the job is recorded as failed, never left stuck on 'building' ---
member_c = _make_member("qa-016a-dispatch-c@example.com")
with patch.object(chat, "_run_chat_turn_engine", side_effect=_fake_engine_crash):
    failing_job_id = chat._queue_route_build(member_c, "website", "תציעי מסלול", [], dict(BASE_TRIP_STATE))
    thread = chat._route_build_threads.get(member_c)
    if thread:
        thread.join(timeout=20)

failed_job = database.get_route_job(failing_job_id)
check("a real engine failure is recorded as status=failed, not left building", failed_job is not None and failed_job["status"] == "failed")
check("the failure reason is captured on the job row", failed_job is not None and bool(failed_job["error"]))
check("thread entry is cleaned up after a failure too", chat._route_build_threads.get(member_c) is None)

# --- 4. The background job's own 150s budget is separate from the website's 90s one ---
check(
    "_claude_call_timeout defaults to the normal 90s budget outside any tracked turn",
    chat._claude_call_timeout() == chat._TURN_TIMEOUT_BUDGET_SECONDS,
)
chat._turn_timing.turn_started = time.time() - 100
chat._turn_timing.budget_seconds = chat._ROUTE_BUILD_TIMEOUT_SECONDS
check(
    "100s into a route-build job (150s budget) the per-call timeout is still non-zero",
    chat._claude_call_timeout() > 0,
)
chat._turn_timing.turn_started = time.time() - 100
chat._turn_timing.budget_seconds = chat._TURN_TIMEOUT_BUDGET_SECONDS
check(
    "the SAME 100s elapsed, but under the ordinary 90s website budget, is already exhausted",
    chat._claude_call_timeout() == 0,
)
chat._turn_timing.turn_started = None
chat._turn_timing.budget_seconds = None

# --- 5. open_route_job_for_member reflects the DB, independent of this process's own dict ---
member_d = _make_member("qa-016a-dispatch-d@example.com")
with patch.object(chat, "_post_claude", side_effect=_slow_post_claude):
    release.clear()
    open_job_id = chat._queue_route_build(member_d, "whatsapp", "תציעי מסלול", [], dict(BASE_TRIP_STATE))
    time.sleep(0.3)
    open_job = database.open_route_job_for_member(member_d)
    check("open_route_job_for_member finds the still-building job", open_job is not None and open_job["id"] == open_job_id)
    release.set()
    thread = chat._route_build_threads.get(member_d)
    if thread:
        thread.join(timeout=20)
check("open_route_job_for_member returns None once it's ready", database.open_route_job_for_member(member_d) is None)

print()
if FAILED:
    print(f"FAILED ({len(FAILED)}): {FAILED}")
    sys.exit(1)
print("ALL 016A-ROUTE-BUILD-DISPATCH-CORE TESTS PASSED")
