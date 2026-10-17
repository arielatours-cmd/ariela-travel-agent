"""QA for a finding (Yosef, right after PR #57 shipped the per-turn
duration logging): source='turn_total' rows (empty model, zero tokens,
one per chat turn regardless of how many real Claude calls happened
inside it) were mixed into usage_summary()'s totals and usage_rows()'s
CSV export alongside genuine API-call rows. Two visible symptoms on
/admin/ai-usage:
1. has_unknown_pricing was permanently True (an empty model string
   matches no pricing table entry).
2. The "calls" count was inflated by one extra, non-API row per turn.

Fixed: usage_summary() and usage_rows() both exclude source='turn_total'
from their main query entirely - it never touches totals, by_source/
by_day/by_member/by_conversation breakdowns, cost, or the calls count.
Its own durations are reported separately: usage_summary() gains a
turn_durations key (count/avg_ms/max_ms/min_ms), and a new
turn_duration_rows() function exports the raw turn_total rows on their
own for anyone who wants them.

Run: python3 tools/qa_turn_total_excluded_from_ai_usage_costs.py
"""
import os
import sys
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("AI_PRICING_JSON", '{"qa-test-model": {"input": 1.0, "output": 2.0, "cache_read": 0.0, "cache_write": 0.0}}')

import database
database.init_db()
import ai_usage

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


with sqlite3.connect(database.DB_PATH) as conn:
    conn.execute("DELETE FROM ai_usage WHERE source IN ('qa_turn_total_test', 'turn_total')")
    conn.commit()

ai_usage.set_ai_usage_context(member_id=5151, trip_id=None, conversation_id=None, is_test=True)

# The shared test DB accumulates rows from every other QA script's own run
# (all flagged is_test=1) - baseline BEFORE this test's own rows, so this
# test asserts the DELTA its own rows cause, not a global absolute count.
baseline = ai_usage.usage_summary(days=1, include_test=True)

# One genuine API-call row (real model, real tokens) ...
ai_usage.record_ai_usage(
    "qa_turn_total_test", "qa-test-model",
    usage=type("U", (), {"input_tokens": 100, "output_tokens": 50,
                          "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0})(),
)
# ... and one turn_total diagnostic row for the SAME turn (empty model,
# zero tokens, just a duration) - exactly what chat_clean()'s wrapper logs.
ai_usage.record_ai_usage("turn_total", "", usage=None, call_duration_ms=4200)
ai_usage.record_ai_usage("turn_total", "", usage=None, call_duration_ms=1800)

summary = ai_usage.usage_summary(days=1, include_test=True)

check("the real API-call row's cost is still correctly estimated",
      summary["total_estimated_cost_usd"] > baseline["total_estimated_cost_usd"])
check("'calls' only goes up by 1 (the real API-call row) - the two "
      "turn_total rows added nothing to it",
      summary["calls"] == baseline["calls"] + 1)
check("'turn_total' never appears as its own bucket in by_source",
      "turn_total" not in summary["by_source"])
check("the real source DOES appear in by_source with calls=1",
      summary["by_source"].get("qa_turn_total_test", {}).get("calls") == 1)

turn_durations = summary.get("turn_durations") or {}
check("turn_durations reports the right count (2 turn_total rows)",
      turn_durations.get("count") == 2)
check("turn_durations reports the right max_ms",
      turn_durations.get("max_ms") == 4200)
check("turn_durations reports the right min_ms",
      turn_durations.get("min_ms") == 1800)
check("turn_durations reports a sane avg_ms",
      turn_durations.get("avg_ms") == 3000)

rows = ai_usage.usage_rows(days=1, include_test=True)
rows_for_this_test = [r for r in rows if r.get("source") in ("qa_turn_total_test", "turn_total")]
check("usage_rows (CSV export) excludes turn_total rows entirely",
      all(r["source"] != "turn_total" for r in rows_for_this_test))
check("usage_rows (CSV export) still includes the real API-call row",
      any(r["source"] == "qa_turn_total_test" for r in rows_for_this_test))

turn_rows = ai_usage.turn_duration_rows(days=1, include_test=True)
check("turn_duration_rows() exports the turn_total rows separately",
      len([r for r in turn_rows if r["source"] == "turn_total" and r["call_duration_ms"] in (4200, 1800)]) == 2)

ai_usage.clear_ai_usage_context()
with sqlite3.connect(database.DB_PATH) as conn:
    conn.execute("DELETE FROM ai_usage WHERE source IN ('qa_turn_total_test', 'turn_total')")
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL TURN-TOTAL-EXCLUDED-FROM-AI-USAGE-COSTS TESTS PASSED")
