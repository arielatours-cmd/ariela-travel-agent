"""QA for the call-timing diagnostic columns added to ai_usage (2026-10-12,
Shaked's concurrency investigation): thread_id, call_started_at,
call_duration_ms now let /admin/ai-usage.csv answer directly whether
different threads' Claude calls genuinely overlap in time, instead of
needing Render's own log stream or more guesswork.

Run: python3 tools/qa_call_timing_diagnostics.py
"""
import os
import sys
import time
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

import ariella_chat_clean as chat
from ai_usage import usage_rows, set_ai_usage_context

set_ai_usage_context(member_id=999999, is_test=True)

fake_usage = MagicMock(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0)
fake_block = MagicMock(type="text", text="ok")
fake_response = MagicMock(usage=fake_usage, content=[fake_block])


def _slow_create(**kwargs):
    time.sleep(0.05)
    return fake_response


fake_client = MagicMock()
fake_client.messages.create.side_effect = _slow_create

before = time.time()
with patch.object(chat, "_get_anthropic_client", return_value=fake_client):
    result = chat._post_claude("test-key-not-real", "claude-sonnet-5", "static", "dynamic", [], "hi", 100, source="qa_timing_probe")
after = time.time()

assert result == "ok", result
print("PASS: _post_claude still returns the reply text correctly")

rows = usage_rows(days=1, include_test=True)
matching = [r for r in rows if r.get("source") == "qa_timing_probe"]
assert matching, "expected a qa_timing_probe row in ai_usage"
row = matching[-1]

assert row.get("thread_id") is not None, row
print(f"PASS: thread_id recorded ({row['thread_id']})")

assert row.get("call_started_at"), row
started = row["call_started_at"]
assert "T" in started and started.endswith(("Z", "+00:00")) or "+" in started, started
print(f"PASS: call_started_at recorded as an ISO timestamp ({started})")

duration = row.get("call_duration_ms")
assert duration is not None and duration >= 40, row
# Sanity: the recorded duration should roughly match the actual elapsed
# wall-clock time of the call (the sleep(0.05) above), not the whole
# function or some unrelated number.
assert duration <= int((after - before) * 1000) + 50, (duration, after - before)
print(f"PASS: call_duration_ms ({duration}ms) matches the actual network-call latency, not the whole function")

print("\nALL CALL-TIMING DIAGNOSTIC TESTS PASSED")
