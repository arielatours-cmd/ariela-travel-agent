"""QA for the background-priority fix after PR #55/#56 (Eran's 502
diagnosis): a chat turn making 1+ sequential Claude calls (the main reply,
state extraction, sometimes a classifier call) had NO timeout anywhere -
only gunicorn's own blanket 120s worker-kill (render.yaml) ever bounded a
hung call, which is an ungraceful crash with zero visibility, not a
response, and surfaces as a bare 502 under load.

Fixed:
1. _claude_call_timeout() computes the remaining per-turn budget (90s,
   clamped to an 8-55s per-call range) from a per-thread turn_started
   timestamp, and _post_claude now passes it as `timeout=` to every
   client.messages.create() call. A timeout raises anthropic.
   APITimeoutError, which EVERY _post_claude/_call_tinkerbell call site
   already wraps in a try/except with a graceful fallback reply (the same
   handling an ordinary transient API failure already gets) - so this is
   safe everywhere it's used, with no call site needing any change.
2. Blueprint-level before_request/after_request hooks (scoped to
   /api/ariella/chat-clean only) log the total turn duration via
   record_ai_usage(source="turn_total", ...) on every request, and a
   logging.warning when a turn crosses _SLOW_TURN_WARNING_MS - giving ops
   visibility into creeping slowness before it becomes a 120s gunicorn
   kill, not after.

Run: python3 tools/qa_per_turn_timeout_cap_and_duration_logging.py
"""
import os
import sys
import time
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import anthropic
import ariella_chat_clean as acc

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# --- 1. No turn tracked (e.g. a one-off script) -> full budget ---
acc._turn_timing.turn_started = None
check("no turn tracked: falls back to the full per-turn budget",
      acc._claude_call_timeout() == acc._TURN_TIMEOUT_BUDGET_SECONDS)

# --- 2. Turn budget already exhausted -> clamped to the floor, never 0/negative ---
acc._turn_timing.turn_started = time.time() - 1000
check("exhausted budget: clamped to the minimum per-call timeout, never <= 0",
      acc._claude_call_timeout() == acc._MIN_CLAUDE_CALL_TIMEOUT_SECONDS)

# --- 3. Fresh turn -> remaining budget exceeds the per-call ceiling, clamped down ---
acc._turn_timing.turn_started = time.time()
check("fresh turn: remaining budget is clamped to the per-call maximum",
      acc._claude_call_timeout() == acc._MAX_CLAUDE_CALL_TIMEOUT_SECONDS)

# --- 4. Partway through the turn -> a real, un-clamped remaining value ---
acc._turn_timing.turn_started = time.time() - 60
mid_budget = acc._claude_call_timeout()
check("partway through a turn: a real mid-range value, not either clamp",
      acc._MIN_CLAUDE_CALL_TIMEOUT_SECONDS < mid_budget < acc._MAX_CLAUDE_CALL_TIMEOUT_SECONDS)

acc._turn_timing.turn_started = None


def _ok_response(text="ok reply"):
    resp = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp.content = [block]
    resp.usage = MagicMock()
    return resp


# --- 5. _post_claude actually passes timeout= through to the SDK call ---
captured_kwargs = {}


def fake_create_capture(**kwargs):
    captured_kwargs.update(kwargs)
    return _ok_response()


client5 = MagicMock()
client5.messages.create.side_effect = fake_create_capture
with patch.object(acc, "_get_anthropic_client", return_value=client5), \
     patch.object(acc, "record_ai_usage"):
    acc._post_claude("fake-key", "claude-x", "system", "", [], "hi", 100, source="test")
check("_post_claude passes a numeric timeout= through to client.messages.create",
      isinstance(captured_kwargs.get("timeout"), (int, float)) and captured_kwargs["timeout"] > 0)

# --- 6. A timeout is never retried (unlike 429/529) - exactly one attempt,
#        and it raises with a message naming the timeout, logging ai_usage
#        with error="timeout" ---
calls6 = {"n": 0}


def fake_create_timeout(**kwargs):
    calls6["n"] += 1
    raise anthropic.APITimeoutError(request=MagicMock())


client6 = MagicMock()
client6.messages.create.side_effect = fake_create_timeout
with patch.object(acc, "_get_anthropic_client", return_value=client6), \
     patch.object(acc, "record_ai_usage") as mock_usage6, \
     patch("time.sleep") as mock_sleep6:
    try:
        acc._post_claude("fake-key", "claude-x", "system", "", [], "hi", 100, source="test")
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        check("a timeout raises RuntimeError mentioning the timeout", "timed out" in str(e))
check("a timeout is never retried - exactly one attempt", calls6["n"] == 1)
check("a timeout never sleeps (unlike the 429/529 retry path)", not mock_sleep6.called)
check("a timeout logs ai_usage with error='timeout'",
      mock_usage6.call_args.kwargs.get("error") == "timeout")

# --- 7. End-to-end: the real chat-clean endpoint, with the main reply
#        timing out - the customer still gets the existing graceful
#        fallback reply (every _call_tinkerbell call site already has this
#        try/except), never a 500/crash. ---
import sqlite3
from datetime import datetime, timezone
import database
database.init_db()
import app as app_module
from werkzeug.security import generate_password_hash

DB = database.DB_PATH
client = app_module.app.test_client()


def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA Turn Timing", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


member_id = _make_member("qa-turn-timing@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id


def _fake_post_claude_timeout_on_reply(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "tinkerbell_reply":
        raise RuntimeError("Claude API call to tinkerbell_reply timed out after 55s")
    if source == "state_extractor":
        return "{}"
    return "תשובה לדוגמה."


with patch.object(acc, "_post_claude", side_effect=_fake_post_claude_timeout_on_reply):
    r7 = client.post("/api/ariella/chat-clean", json={
        "message": "שלום", "history": [], "trip_state": {},
    })
check("a timed-out main reply still returns 200, not a crash",
      r7.status_code == 200)
reply7 = (r7.get_json() or {}).get("reply") or ""
check("a timed-out main reply still returns SOME reply text to the customer",
      bool(reply7.strip()))

# --- 8. Total-turn-duration logging: a normal, fully-mocked-fast turn
#        still logs a source="turn_total" ai_usage row with a real
#        call_duration_ms. ---
turn_total_calls = []
_orig_record_ai_usage = acc.record_ai_usage


def _capture_record_ai_usage(source, model, **kwargs):
    if source == "turn_total":
        turn_total_calls.append(kwargs)
    return _orig_record_ai_usage(source, model, **kwargs)


def _fake_post_claude_fast(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return "{}"
    return "תשובה לדוגמה."


with patch.object(acc, "_post_claude", side_effect=_fake_post_claude_fast), \
     patch.object(acc, "record_ai_usage", side_effect=_capture_record_ai_usage):
    r8 = client.post("/api/ariella/chat-clean", json={
        "message": "שלום", "history": [], "trip_state": {},
    })
check("a normal turn logs exactly one source='turn_total' ai_usage row",
      len(turn_total_calls) == 1)
if turn_total_calls:
    check("the turn_total row has a real, non-negative call_duration_ms",
          isinstance(turn_total_calls[0].get("call_duration_ms"), int) and turn_total_calls[0]["call_duration_ms"] >= 0)
    check("the turn_total row has a call_started_at timestamp",
          bool(turn_total_calls[0].get("call_started_at")))

# --- 9. Regression: /api/ariella/resume (a different route on the same
#        blueprint, never wrapped) never touches turn_started at all. ---
acc._turn_timing.turn_started = "sentinel-should-not-be-touched"
r9 = client.get("/api/ariella/resume")
check("an unrelated route on the same blueprint never touches turn_started",
      acc._turn_timing.turn_started == "sentinel-should-not-be-touched")
acc._turn_timing.turn_started = None

# --- 10. The actual live routing: ariella_chat_v2's own registration of
#        /api/ariella/chat-clean (which, per registration order, is the one
#        that genuinely serves this path - see the comment on chat_clean()
#        itself) also goes through the new wrapper, since it calls
#        chat_clean() by name. Confirmed indirectly by check 8 above
#        (that request already went through this exact path) - this check
#        just pins down which blueprint actually serves it, so a future
#        reordering in app.py is caught here instead of silently going
#        back to a blueprint hook that would never fire again. ---
with app_module.app.test_request_context("/api/ariella/chat-clean", method="POST"):
    check("ariella_chat_v2 (not this blueprint's own rule) is what actually serves this path",
          acc.request.blueprint == "ariella_chat_v2")

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL PER-TURN-TIMEOUT-CAP-AND-DURATION-LOGGING TESTS PASSED")
