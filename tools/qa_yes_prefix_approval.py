"""QA for round-8 item #6 (Shaked, 2026-10-16, qa/reports/2026-10-16-round8-conversation.md):
"כן, מאשרת" (right after the flight summary ended in "אם כל הפרטים נכונים,
כתבי מאשרת") was NOT recognized as approval - Ariella replied "לא הבנתי,
האם התכוונת לאשר? אם כן, כתבי מאשרת" instead of launching the search.

Root cause: _approval_trigger in ariella_chat_clean.py requires the message
to be EXACTLY "מאשר"/"מאשרת" (nothing else). "כן, מאשרת" ("yes, I confirm") is
a completely natural, common way to phrase the same approval, but it isn't
an exact match, so it fell through to _looks_like_approval_typo - whose
fuzzy difflib match against the compacted string ("כןמאשרת" vs "מאשרת")
scores high enough (>=0.72) to be treated as a near-miss TYPO rather than a
genuine approval, producing the "did you mean to confirm?" clarification
instead of actually approving.

Fixed: _approval_trigger now also strips a leading "כן" (with its
separating punctuation/whitespace) and rechecks the remainder against the
same exact two words, before falling through to the typo path. A bare "כן"
with nothing else still does NOT approve (unlike the real approval words,
it's not a search-launch event).

Run: python3 tools/qa_yes_prefix_approval.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import ariella_chat_clean as chat

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


SUMMARY_HISTORY = [{"role": "assistant", "content": "אם כל הפרטים נכונים, כתבי מאשרת."}]
STATE = {"ready_for_summary": True}

# --- Shaked's exact live repro ---
check("'כן, מאשרת' (with comma) IS approval",
      chat._approval_trigger("כן, מאשרת", SUMMARY_HISTORY, STATE) is True)
check("'כן מאשרת' (no comma, just space) IS approval",
      chat._approval_trigger("כן מאשרת", SUMMARY_HISTORY, STATE) is True)
check("the masculine form 'כן, מאשר' IS approval too",
      chat._approval_trigger("כן, מאשר", SUMMARY_HISTORY, {"ready_for_summary": True}) is True)
def would_show_typo_clarifier(message, state, history):
    """Mirrors chat_clean()'s actual gate: the typo clarifier only ever
    fires when _approval_trigger itself did NOT already recognize approval
    this turn - so once _approval_trigger accepts a yes-prefixed message,
    the fuzzy typo check downstream never even runs for it."""
    if chat._approval_trigger(message, history, state):
        return False
    return chat._looks_like_approval_typo(message, state, history)


check("'כן, מאשרת' no longer reaches the 'did you mean to confirm?' clarifier",
      would_show_typo_clarifier("כן, מאשרת", STATE, SUMMARY_HISTORY) is False)

# --- Regression guards ---
check("regression: bare exact 'מאשרת' still approves",
      chat._approval_trigger("מאשרת", SUMMARY_HISTORY, STATE) is True)
check("regression: bare exact 'מאשר' still approves",
      chat._approval_trigger("מאשר", SUMMARY_HISTORY, STATE) is True)
check("regression: a bare 'כן' alone must NOT approve",
      chat._approval_trigger("כן", SUMMARY_HISTORY, STATE) is False)
check("regression: unrelated text with 'כן' inside is not approval",
      chat._approval_trigger("כן, אני רוצה גם לינה", SUMMARY_HISTORY, STATE) is False)
check("regression: a genuine typo ('אשרת') still routes through the typo path, not approval",
      chat._approval_trigger("אשרת", SUMMARY_HISTORY, STATE) is False
      and chat._looks_like_approval_typo("אשרת", STATE, SUMMARY_HISTORY) is True)
check("regression: post-flight continuation still blocks a stray 'כן, מאשרת' for a non-flight session",
      chat._approval_trigger("כן, מאשרת", SUMMARY_HISTORY,
                              {"post_flight_continuation": True, "active_session": "lodging"}) is False)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL YES-PREFIX-APPROVAL TESTS PASSED")
