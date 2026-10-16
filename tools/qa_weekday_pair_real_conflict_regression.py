"""Standalone regression guard for a specific, critical false-negative Shaked
caught comparing PR #29 against PR #30 (qa/cases.json on the shaked branch,
case id "weekday-pair-real-conflict-still-asked", commit d4b88ca): a genuine
weekday/date contradiction must never be silently swallowed.

PR #29 alone (commit e2324e7) failed this exact case: history=[{"role":
"user", "content": "אני רוצה לטוס מחמישי עד שבת"}], message="19.9 עד 30.9"
(19.9.2027 is actually a Sunday) returned None instead of asking for
clarification. Root cause: an earlier attempt at a structural fix in
_weekday_pair_conflict (requiring a date in the same historical message as
the weekday pair - see tools/qa_weekday_conflict_no_repeat_loop.py's own
docstring for why that check was wrong and reverted) was still present in
e2324e7 even though it had already been removed from later work - "אני
רוצה לטוס מחמישי עד שבת" has no date in that same message, so the stray
check silently discarded a real conflict instead of flagging it.

This file exists as its own small, independently runnable script (rather
than folded into tools/qa_weekday_conflict_no_repeat_loop.py, which already
covers the same case among others) specifically so this one regression -
"a real weekday/date conflict goes unasked" - has a dedicated, easy-to-spot
guard of its own.

Run: python3 tools/qa_weekday_pair_real_conflict_regression.py
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import ariella_chat_clean as chat

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# --- Shaked's exact qa/cases.json case: weekday-pair-real-conflict-still-asked ---
history = [{"role": "user", "content": "אני רוצה לטוס מחמישי עד שבת"}]
result = chat._weekday_date_conflict("19.9 עד 30.9", history)
check("a genuine weekday/date contradiction is never silently swallowed",
      bool(result))
check("the clarification correctly names the real weekday (19.9.2027 is a Sunday)",
      bool(result) and "יוצא ביום ראשון" in result)
check("the clarification quotes back what the customer actually asked for",
      bool(result) and "חמישי עד שבת" in result)

# --- Sanity: 19.9.2027 is in fact a Sunday - the test's own premise must
#     hold, independent of the function under test ---
check("test premise: 19.9.2027 is a Sunday", date(2027, 9, 19).weekday() == 6)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL WEEKDAY-PAIR-REAL-CONFLICT-REGRESSION TESTS PASSED")
