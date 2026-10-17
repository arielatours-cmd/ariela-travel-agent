"""QA for task 016a Stage 5: the background-route-build edge cases from
Ofek's spec (section 6) - a message arriving during a build (queued, then
replayed in order once the route is ready), "מאשרת" arriving during a
build (never queued - a fresh approval is needed once the route is
actually shown), a genuine double failure (one automatic retry, then a
yes/no "try again?" question composed in Ariella's own words, answered by
MEANING on the customer's next message), and a stale 'building' row left
over from a dead process/restart being reclaimed as a failure instead of
blocking the member forever.

Run: python3 tools/qa_016a_stage5_edge_cases.py
"""
import json
import os
import sys
import sqlite3
from datetime import datetime, timedelta, timezone
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
            ("QA 016a Stage5", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


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


def _login(member_id):
    with client.session_transaction() as sess:
        sess["member_id"] = member_id


# =====================================================================
# 1. Message arriving during a build: queued, acked, no second job, then
#    replayed (in order) once the route is ready.
# =====================================================================
member1 = _make_member("qa-016a-s5-queue@example.com")
_login(member1)

import threading as _threading
release1 = _threading.Event()


def _fake_post_claude_slow_then_update(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "route_ack":
        return "אני בונה לכם את המסלול עכשיו!"
    if source == "route_build_queued_ack":
        return "קלטתי, אתייחס לזה ברגע שהמסלול מוכן!"
    if source == "state_extractor":
        return json.dumps({"trip_update": {}})
    if source == "tinkerbell_reply" and "בלי מוזיאונים" not in str(message or ""):
        # The MAIN route-build call blocks here until the test has sent its
        # second message and verified it was queued, not started as a
        # second build - proving the job is genuinely still 'building' at
        # that moment, not a timing coincidence.
        release1.wait(timeout=10)
    if "בלי מוזיאונים" in str(message or ""):
        return "עדכנתי - המסלול עכשיו בלי מוזיאונים."
    return "יום 1: נחיתה ברומא. יום 2: סיור בעיר העתיקה."


with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_slow_then_update):
    resp1 = client.post("/api/ariella/chat-clean", json={"message": "תציעי מסלול בבקשה", "history": [], "trip_state": ROUTE_READY_TRIP_STATE})
    job_id = resp1.get_json().get("route_build_job_id")
    check("dispatch: a job id is returned", isinstance(job_id, int))

    import time as _time
    _time.sleep(0.3)  # let the background thread actually start and reach the blocked call

    resp2 = client.post("/api/ariella/chat-clean", json={"message": "בלי מוזיאונים בבקשה", "history": [], "trip_state": ROUTE_READY_TRIP_STATE})
    data2 = resp2.get_json()
    check("a message during the build never gets its own job id", data2.get("route_build_job_id") is None)
    check("a message during the build gets a short aside reply", data2.get("reply") == "קלטתי, אתייחס לזה ברגע שהמסלול מוכן!")

    job_after_queue = database.get_route_job(job_id)
    check("the message was appended to the job's queue, not lost", job_after_queue["queued_messages"] == ["בלי מוזיאונים בבקשה"])
    check("no second background thread/job was started for this member", database.open_route_job_for_member(member1)["id"] == job_id)

    release1.set()
    thread = chat._route_build_threads.get(member1)
    if thread:
        thread.join(timeout=20)

final_job = database.get_route_job(job_id)
check("the main job reaches status=ready", final_job["status"] == "ready")
check("the main job's own reply is the route itself", "יום 1" in (final_job["result_reply"] or ""))
check("the queued message was replayed and its own reply recorded", any("בלי מוזיאונים" in r or "מוזיאונים" in r for r in final_job["queued_replies"]))

status_resp = client.get(f"/api/ariella/route-status/{job_id}")
status_data = status_resp.get_json()
check("the status endpoint exposes queued_replies for the client to show after the route", len(status_data.get("queued_replies") or []) == 1)

# =====================================================================
# 2. "מאשרת" arriving during a build: a premature-approval aside, NEVER
#    queued for later replay.
# =====================================================================
member2 = _make_member("qa-016a-s5-approval@example.com")
_login(member2)


release2 = _threading.Event()


def _fake_post_claude_approval(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "route_ack":
        return "אני בונה לכם את המסלול עכשיו!"
    if source == "route_build_premature_approval_ack":
        return "המסלול כמעט מוכן, אציג לך אותו לאישור בעוד רגע!"
    if source == "state_extractor":
        return json.dumps({"trip_update": {}})
    if source == "tinkerbell_reply":
        release2.wait(timeout=10)
    return "יום 1: נחיתה. יום 2: סיור."


with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_approval):
    resp3 = client.post("/api/ariella/chat-clean", json={"message": "תציעי מסלול בבקשה", "history": [], "trip_state": ROUTE_READY_TRIP_STATE})
    job_id_2 = resp3.get_json().get("route_build_job_id")
    _time.sleep(0.3)

    resp4 = client.post("/api/ariella/chat-clean", json={"message": "מאשרת", "history": [], "trip_state": ROUTE_READY_TRIP_STATE})
    data4 = resp4.get_json()
    check("'מאשרת' during a build never gets a job id of its own", data4.get("route_build_job_id") is None)
    check("'מאשרת' during a build gets the premature-approval aside", data4.get("reply") == "המסלול כמעט מוכן, אציג לך אותו לאישור בעוד רגע!")

    job2_after = database.get_route_job(job_id_2)
    check("'מאשרת' is NEVER queued for replay (approving an unseen route is meaningless)", job2_after["queued_messages"] == [])

    release2.set()
    thread2 = chat._route_build_threads.get(member2)
    if thread2:
        thread2.join(timeout=20)

# =====================================================================
# 3. A stale 'building' row (simulating a dead process/restart) is
#    reclaimed as a failure, never blocking the member forever.
# =====================================================================
member3 = _make_member("qa-016a-s5-stale@example.com")
_login(member3)

stale_job_id = database.create_route_job(member3, "website", "תציעי מסלול", [], ROUTE_READY_TRIP_STATE)
stale_started_at = (datetime.now(timezone.utc) - timedelta(seconds=200)).isoformat()
with sqlite3.connect(DB) as conn:
    conn.execute("UPDATE route_jobs SET started_at=? WHERE id=?", (stale_started_at, stale_job_id))
    conn.commit()


def _fake_post_claude_fresh_build(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "route_ack":
        return "אני בונה לכם מסלול חדש עכשיו!"
    if source == "state_extractor":
        return json.dumps({"trip_update": {}})
    return "יום 1: מסלול חדש."


with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_fresh_build):
    resp5 = client.post("/api/ariella/chat-clean", json={"message": "תציעי מסלול בבקשה", "history": [], "trip_state": ROUTE_READY_TRIP_STATE})
    data5 = resp5.get_json()
    new_job_id = data5.get("route_build_job_id")
    thread3 = chat._route_build_threads.get(member3)
    if thread3:
        thread3.join(timeout=20)

check("a stale 'building' row never blocks a fresh build from starting", isinstance(data5.get("route_build_job_id"), int))
check("the stale row itself is reclaimed as failed", database.get_route_job(stale_job_id)["status"] == "failed")
check("the fresh build (post-reclaim) completes normally", database.get_route_job(new_job_id)["status"] == "ready")

# =====================================================================
# 4. A genuine double failure: one automatic retry, then a yes/no
#    retry question, answered by MEANING on the next message (yes ->
#    new job; no -> falls through to ordinary synchronous processing).
# =====================================================================
member4 = _make_member("qa-016a-s5-retry-yes@example.com")
_login(member4)


def _fake_ack_only_post_claude(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    # _call_tinkerbell's own internal try/except already absorbs a raised
    # _post_claude exception into a graceful fallback reply (see
    # _claude_call_timeout's docstring) - raising there can never simulate
    # an engine-level failure for this test. The genuine failure instead
    # comes from patching _run_chat_turn_engine itself, below.
    if source == "route_ack":
        return "אני בונה לכם את המסלול עכשיו!"
    if source == "route_build_failure_retry_question":
        return "הייתה לי בעיה בבניית המסלול - לנסות שוב?"
    return "אוקיי"


_engine_call_count = {"n": 0}


def _fake_engine_fails_twice_then_succeeds(member_id, message, history, trip_state, channel=None):
    if message == "תציעי מסלול בבקשה":
        _engine_call_count["n"] += 1
        if _engine_call_count["n"] <= 2:
            raise RuntimeError("simulated persistent engine crash")
    return chat.jsonify({
        'status': 'success', 'agent': 'Tinkerbell', 'engine_version': chat.ENGINE_VERSION,
        'reply': 'יום 1: מסלול לאחר ניסיון חוזר.', 'trip_update': trip_state,
        'start_flight_search': False,
    })


with patch.object(chat, "_post_claude", side_effect=_fake_ack_only_post_claude), \
     patch.object(chat, "_run_chat_turn_engine", side_effect=_fake_engine_fails_twice_then_succeeds):
    resp6 = client.post("/api/ariella/chat-clean", json={"message": "תציעי מסלול בבקשה", "history": [], "trip_state": ROUTE_READY_TRIP_STATE})
    failing_job_id = resp6.get_json().get("route_build_job_id")
    thread4 = chat._route_build_threads.get(member4)
    if thread4:
        thread4.join(timeout=20)

failed_job = database.get_route_job(failing_job_id)
check("a double failure (both attempts) is recorded as status=failed", failed_job["status"] == "failed")
check("the job's own attempt counter reached 2 (one automatic retry happened)", failed_job["attempt"] == 2)
check("a yes/no retry question (Ariella's own words) is stored as the job's reply", failed_job["result_reply"] == "הייתה לי בעיה בבניית המסלול - לנסות שוב?")
check("retry_resolved starts false - the question is still pending an answer", failed_job["retry_resolved"] is False)


def _fake_interpret_yes(key, model, history, message, question_text):
    return "yes"


with patch.object(chat, "_interpret_yes_no", side_effect=_fake_interpret_yes), \
     patch.object(chat, "_post_claude", side_effect=_fake_post_claude_fresh_build):
    resp7 = client.post("/api/ariella/chat-clean", json={"message": "כן בבקשה", "history": [], "trip_state": ROUTE_READY_TRIP_STATE})
    data7 = resp7.get_json()
    new_retry_job_id = data7.get("route_build_job_id")
    thread5 = chat._route_build_threads.get(member4)
    if thread5:
        thread5.join(timeout=20)

check("answering 'yes' (by meaning) to the retry question starts a fresh job", isinstance(new_retry_job_id, int))
check("the old failed job is marked retry_resolved once answered", database.get_route_job(failing_job_id)["retry_resolved"] is True)
check("the retried build completes normally", new_retry_job_id is not None and database.get_route_job(new_retry_job_id)["status"] == "ready")

# --- "No" answer: falls through to ordinary synchronous processing ---
member5 = _make_member("qa-016a-s5-retry-no@example.com")
_login(member5)

_engine_call_count_2 = {"n": 0}


def _fake_engine_fails_twice_then_succeeds_2(member_id, message, history, trip_state, channel=None):
    if message == "תציעי מסלול בבקשה":
        _engine_call_count_2["n"] += 1
        if _engine_call_count_2["n"] <= 2:
            raise RuntimeError("simulated persistent engine crash")
    return chat.jsonify({
        'status': 'success', 'agent': 'Tinkerbell', 'engine_version': chat.ENGINE_VERSION,
        'reply': 'יום 1: מסלול.', 'trip_update': trip_state, 'start_flight_search': False,
    })


with patch.object(chat, "_post_claude", side_effect=_fake_ack_only_post_claude), \
     patch.object(chat, "_run_chat_turn_engine", side_effect=_fake_engine_fails_twice_then_succeeds_2):
    resp8 = client.post("/api/ariella/chat-clean", json={"message": "תציעי מסלול בבקשה", "history": [], "trip_state": ROUTE_READY_TRIP_STATE})
    failing_job_id_2 = resp8.get_json().get("route_build_job_id")
    thread6 = chat._route_build_threads.get(member5)
    if thread6:
        thread6.join(timeout=20)


def _fake_interpret_no(key, model, history, message, question_text):
    return "no"


def _fake_post_claude_ordinary_question(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({"trip_update": {}})
    return "בטח, ספרו לי עוד על מה שאתם אוהבים לעשות."


with patch.object(chat, "_interpret_yes_no", side_effect=_fake_interpret_no), \
     patch.object(chat, "_post_claude", side_effect=_fake_post_claude_ordinary_question):
    resp9 = client.post("/api/ariella/chat-clean", json={"message": "לא תודה, בוא נמשיך", "history": [], "trip_state": ROUTE_READY_TRIP_STATE})
    data9 = resp9.get_json()

check("answering 'no' never starts a new job", data9.get("route_build_job_id") is None)
check("'no' falls through to an ordinary synchronous reply", data9.get("reply") == "בטח, ספרו לי עוד על מה שאתם אוהבים לעשות.")
check("the old failed job is marked retry_resolved on 'no' too", database.get_route_job(failing_job_id_2)["retry_resolved"] is True)

# An unrelated LATER message must never re-trigger the (already-resolved) question.
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_ordinary_question) as mock_post:
    resp10 = client.post("/api/ariella/chat-clean", json={"message": "עוד שאלה סתם", "history": [], "trip_state": ROUTE_READY_TRIP_STATE})
check("a later unrelated message is never mistaken for a retry answer again", resp10.get_json().get("reply") == "בטח, ספרו לי עוד על מה שאתם אוהבים לעשות.")

print()
if FAILED:
    print(f"FAILED ({len(FAILED)}): {FAILED}")
    sys.exit(1)
print("ALL 016A-STAGE5-EDGE-CASES TESTS PASSED")
