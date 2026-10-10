"""QA for task 005a - AI usage tracking.

Mocks client.messages.create (via _get_anthropic_client) to return a fixed
usage object, then verifies: a normal call writes a row with the right
context; an API error writes an error row with zero tokens; cost estimation
matches a test pricing table; and a DB write failure never raises out of
_post_claude (the chat turn must survive it).

Run: python3 tools/qa_ai_usage_tracking.py
"""
import os
import sys
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("AI_PRICING_JSON", '{"qa-test-model": {"input": 1.0, "output": 2.0, "cache_read": 0.1, "cache_write": 1.25}}')

import anthropic
import database
import ai_usage
import ariella_chat_clean as acc

database.init_db()
FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


def fake_usage(input_tokens=100, output_tokens=50, cache_read=10, cache_write=5):
    return SimpleNamespace(
        input_tokens=input_tokens, output_tokens=output_tokens,
        cache_read_input_tokens=cache_read, cache_creation_input_tokens=cache_write,
    )


def fake_client(content_text="ok", usage=None):
    client = SimpleNamespace()
    response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text=content_text)],
        usage=usage or fake_usage(),
    )
    client.messages = SimpleNamespace(create=lambda **kw: response)
    return client


# 1. A normal call writes a row with member_id/conversation_id/source and tokens > 0.
with sqlite3.connect(database.DB_PATH) as conn:
    conn.execute("DELETE FROM ai_usage WHERE source='qa_test_source'")
    conn.commit()

ai_usage.set_ai_usage_context(member_id=4242, trip_id=99, conversation_id=7, is_test=True)
with patch.object(acc, "_get_anthropic_client", return_value=fake_client(usage=fake_usage(100, 50, 10, 5))):
    reply = acc._post_claude("k", "qa-test-model", "system", "", [], "hi", 100, source="qa_test_source")
check("reply returned normally", reply == "ok")

with sqlite3.connect(database.DB_PATH) as conn:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM ai_usage WHERE source='qa_test_source' ORDER BY id DESC LIMIT 1"
    ).fetchone()
check("row was written", row is not None)
if row:
    check("member_id captured", row["member_id"] == 4242)
    check("trip_id captured", row["trip_id"] == 99)
    check("conversation_id captured", row["conversation_id"] == 7)
    check("is_test captured", row["is_test"] == 1)
    check("input_tokens > 0", row["input_tokens"] == 100)
    check("output_tokens > 0", row["output_tokens"] == 50)
    check("cache_read_input_tokens captured", row["cache_read_input_tokens"] == 10)
    check("cache_creation_input_tokens captured", row["cache_creation_input_tokens"] == 5)
    check("no error on success", row["error"] is None)

# 2. estimate_cost_usd matches the test pricing table.
expected_cost = (100 * 1.0 + 50 * 2.0 + 10 * 0.1 + 5 * 1.25) / 1_000_000
got_cost = ai_usage.estimate_cost_usd(dict(row)) if row else None
check("cost estimate matches test pricing", got_cost is not None and abs(got_cost - expected_cost) < 1e-12)

# 3. A model with no pricing entry -> cost is None, not a guess/crash.
unknown = {"model": "no-such-model", "input_tokens": 10, "output_tokens": 10, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
check("unknown model -> cost None (no guess)", ai_usage.estimate_cost_usd(unknown) is None)

# 4. An API error writes a row with error set and zero tokens, and still raises RuntimeError.
ai_usage.set_ai_usage_context(member_id=4242, trip_id=99, conversation_id=7, is_test=True)


def failing_create(**kw):
    request = SimpleNamespace()
    response = SimpleNamespace(status_code=529, headers={}, request=request)
    raise anthropic.APIStatusError("overloaded", response=response, body=None)


err_client = SimpleNamespace(messages=SimpleNamespace(create=failing_create))
raised = False
with patch.object(acc, "_get_anthropic_client", return_value=err_client):
    try:
        acc._post_claude("k", "qa-test-model", "system", "", [], "hi", 100, source="qa_test_source")
    except RuntimeError:
        raised = True
check("API error still raises RuntimeError to the caller", raised)

with sqlite3.connect(database.DB_PATH) as conn:
    conn.row_factory = sqlite3.Row
    err_row = conn.execute(
        "SELECT * FROM ai_usage WHERE source='qa_test_source' AND error IS NOT NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
check("error row was written", err_row is not None)
if err_row:
    check("error row has zero tokens", err_row["input_tokens"] == 0 and err_row["output_tokens"] == 0)
    check("error column set", bool(err_row["error"]))

# 5. A DB write failure inside record_ai_usage must never raise - the chat
# turn must survive it (this is the single most important property here).
ai_usage.set_ai_usage_context(member_id=1, trip_id=None, conversation_id=None, is_test=True)
with patch.object(acc, "_get_anthropic_client", return_value=fake_client()), \
     patch.object(ai_usage, "connection", side_effect=RuntimeError("DB is locked")):
    try:
        reply2 = acc._post_claude("k", "qa-test-model", "system", "", [], "hi", 100, source="qa_test_source")
        survived = True
    except Exception:
        survived = False
check("a DB failure while recording usage never breaks the chat turn", survived)

ai_usage.clear_ai_usage_context()

with sqlite3.connect(database.DB_PATH) as conn:
    conn.execute("DELETE FROM ai_usage WHERE source='qa_test_source'")
    conn.commit()

print()
if FAILED:
    print(f"FAILED ({len(FAILED)}): {FAILED}")
    sys.exit(1)
print("ALL CHECKS PASSED")
