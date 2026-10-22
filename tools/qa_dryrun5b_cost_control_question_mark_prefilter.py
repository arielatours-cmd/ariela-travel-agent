"""QA for dry-run 5b item 6 (Shlomo's explicit cost-control suggestion,
22.10.2026, qa/reports/2026-10-22-dryrun5b.md): the classifier call behind
_guided_question_actually_asked (shared by _guard_baggage_type_self_picked
and _guard_accessibility_question_skipped) ran 40 times across 52 turns in
the dry-run 5b report (~18 retries, 70 tinkerbell_reply calls vs 52 turns -
nearly double the normal rate).

Fix: a cheap, purely structural pre-filter (never a phrase/word-list
judgment about the model's own content - a question mark's presence is
punctuation, not meaning) skips the classifier call entirely whenever the
reply contains no "?" at all - a reply with no question mark anywhere
cannot genuinely be asking anything, about any topic, so there is nothing
left for the model to usefully judge; it goes straight to "not asked", no
call needed. The classifier is still called whenever a "?" IS present,
since only the model can judge whether that question is genuinely about
the right topic or something else entirely.

Run: python3 tools/qa_dryrun5b_cost_control_question_mark_prefilter.py
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import ariella_chat_clean as chat  # noqa: E402

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


KEY = os.getenv("ANTHROPIC_API_KEY", "test-key-not-real")
MODEL = "claude-sonnet-5"


def _fake_classifier_says(answer):
    def _fake(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
        if source == "classifier":
            return '{"asked": %s}' % ("true" if answer else "false")
        return "{}"
    return _fake


# =====================================================================
# No "?" anywhere: the classifier is never called, straight to False.
# =====================================================================
calls = []
with patch.object(chat, "_post_claude", side_effect=lambda *a, **kw: (calls.append(1), "{}")[1]):
    result_no_mark = chat._guided_question_actually_asked(KEY, MODEL, "אפשר לכתוב כאן בקצרה על מה מדובר", "נגישות")
check("cost control: a reply with NO question mark at all skips the classifier call entirely",
      not calls)
check("cost control: a reply with no question mark is treated as 'not asked' (structurally correct - "
      "nothing resembling a real question is even present)",
      result_no_mark is False)

# =====================================================================
# A "?" IS present: the classifier is still called (punctuation alone
# never settles whether it's about the RIGHT topic).
# =====================================================================
calls2 = []


def _counting_fake(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "classifier":
        calls2.append(message)
        return '{"asked": true}'
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_counting_fake):
    result_with_mark = chat._guided_question_actually_asked(KEY, MODEL, "איזו כבודה תרצו לקחת?", "כבודה")
check("cost control: a reply that DOES contain a question mark still calls the classifier",
      len(calls2) == 1)
check("regression: the classifier's own answer is still honored when it IS called",
      result_with_mark is True)

# =====================================================================
# A "?" present but about the wrong topic - the classifier (not the
# pre-filter) is the one that correctly says False; the pre-filter never
# short-circuits a reply that has real punctuation to judge.
# =====================================================================
with patch.object(chat, "_post_claude", side_effect=_fake_classifier_says(False)):
    result_wrong_topic = chat._guided_question_actually_asked(KEY, MODEL, "מה התקציב שלכם לאדם לטיסה?", "כבודה")
check("regression: a real question about the WRONG topic still reaches the classifier, "
      "which correctly says 'not asked' about the intended topic",
      result_wrong_topic is False)

# =====================================================================
# Empty reply / empty key: unaffected, still fails open (True), before
# the question-mark check is even reached.
# =====================================================================
check("regression: an empty reply still fails open (True), unaffected by the new pre-filter",
      chat._guided_question_actually_asked(KEY, MODEL, "", "כבודה") is True)
check("regression: an empty key still fails open (True), unaffected by the new pre-filter",
      chat._guided_question_actually_asked("", MODEL, "איזו כבודה תרצו לקחת?", "כבודה") is True)


if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DRYRUN5B-COST-CONTROL-QUESTION-MARK-PREFILTER TESTS PASSED")
