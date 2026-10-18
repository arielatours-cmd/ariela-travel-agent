"""QA for Shaked's bug 1 (2026-10-12 live QA, most severe/🔴): 6 customers
messaging Ariella at once made 4/6 chat turns fail with a generic "technical
glitch", even though sending them one at a time all succeeded. Root cause:
_post_claude (ariella_chat_clean.py) converted ANY anthropic.APIStatusError
straight into a fatal RuntimeError with zero retry beyond the SDK's own
internal default, so a transient 429 (rate_limit_error) or 529
(overloaded_error) under a genuine concurrent burst killed the whole turn.
This covers the new one-retry-then-raise behavior - never a real network
call, everything mocked.

Run: python3 tools/qa_claude_retry.py
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import anthropic
import ariella_chat_clean as acc


def _status_error(code):
    resp = MagicMock()
    resp.status_code = code
    resp.headers = {}
    return anthropic.APIStatusError("error", response=resp, body={"error": {"message": "error"}})


def _ok_response(text="ok reply"):
    resp = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp.content = [block]
    resp.usage = MagicMock()
    return resp


# --- 1. A retryable error (429) on the first attempt succeeds on the second ---
for code in (429, 529):
    calls = {"n": 0}

    def fake_create(_code=code, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _status_error(_code)
        return _ok_response()

    client = MagicMock()
    client.messages.create.side_effect = fake_create
    with patch.object(acc, "_get_anthropic_client", return_value=client), \
         patch.object(acc, "record_ai_usage"), \
         patch("time.sleep") as mock_sleep:
        result = acc._post_claude("fake-key", "claude-x", "system", "", [], "hi", 100, source="test")
    assert result == "ok reply", result
    assert calls["n"] == 2, calls
    assert mock_sleep.called
    print(f"PASS: {code} on attempt 1 -> one retry -> succeeds on attempt 2")

# --- 2. A non-retryable error (400) fails immediately, no retry ---
calls2 = {"n": 0}


def fake_create_400(**kwargs):
    calls2["n"] += 1
    raise _status_error(400)


client2 = MagicMock()
client2.messages.create.side_effect = fake_create_400
with patch.object(acc, "_get_anthropic_client", return_value=client2), \
     patch.object(acc, "record_ai_usage") as mock_usage2, \
     patch("time.sleep") as mock_sleep2:
    try:
        acc._post_claude("fake-key", "claude-x", "system", "", [], "hi", 100, source="test")
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "400" in str(e), str(e)
assert calls2["n"] == 1, calls2
assert not mock_sleep2.called
assert mock_usage2.call_args.kwargs.get("error") == 400
print("PASS: non-retryable 400 fails immediately (no wasted retry) and still logs ai_usage")

# --- 3. A persistent 429 (fails on both attempts) still raises after exactly 2 total calls ---
calls3 = {"n": 0}


def fake_create_always_429(**kwargs):
    calls3["n"] += 1
    raise _status_error(429)


client3 = MagicMock()
client3.messages.create.side_effect = fake_create_always_429
with patch.object(acc, "_get_anthropic_client", return_value=client3), \
     patch.object(acc, "record_ai_usage"), \
     patch("time.sleep"):
    try:
        acc._post_claude("fake-key", "claude-x", "system", "", [], "hi", 100, source="test")
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "429" in str(e), str(e)
assert calls3["n"] == 2, calls3
print("PASS: persistent 429 still fails after exactly 2 total attempts - never retries forever")

# --- 4. Success on the very first attempt never sleeps/retries at all ---
calls4 = {"n": 0}


def fake_create_ok(**kwargs):
    calls4["n"] += 1
    return _ok_response("first try")


client4 = MagicMock()
client4.messages.create.side_effect = fake_create_ok
with patch.object(acc, "_get_anthropic_client", return_value=client4), \
     patch.object(acc, "record_ai_usage"), \
     patch("time.sleep") as mock_sleep4:
    result4 = acc._post_claude("fake-key", "claude-x", "system", "", [], "hi", 100, source="test")
assert result4 == "first try"
assert calls4["n"] == 1, calls4
assert not mock_sleep4.called
print("PASS: a clean first attempt makes exactly one call, no retry overhead")

print("\nALL CLAUDE RETRY (concurrency bug 1) TESTS PASSED")
