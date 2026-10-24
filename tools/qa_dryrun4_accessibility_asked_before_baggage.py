"""QA for dry-run 4 finding 4 (Shaked/Shlomo, 22.10.2026, qa-dryrun branch,
qa/dryrun/2026-10-22-dr4-ABCEF/dr4_F.log, Prague):

Real transcript: guided.current_question was "accessibility" (dates and
travelers both already answered from the opening message), and the
dynamic_hint correctly told Tinkerbell to ask the accessibility yes/no.
Instead, her free text skipped straight to baggage ("לגבי כבודה - איזו
כבודה תצטרכו לקחת?") - no accessibility question anywhere in the reply.
_guided_redirect_field's existing safety net recovered the baggage answer
correctly on the next turn (nothing was lost from state) - but the
customer still experienced baggage asked BEFORE accessibility, the wrong
order the guided flow exists to guarantee.

REWORKED per Shaked's review of the first version (round 12, e033a3b):
the original fix scanned the reply for marker words ("נגישות"/"התאמה")
and substituted a fixed fallback sentence when they were missing, plus a
re.search on dates in the reply text as a skip condition - all forbidden
(no phrase lists on model output, no regex scanning/matching the model's
own output to decide whether to override it, no fixed sentences replacing
the model's answer). Fixed: _guided_question_actually_asked (a short model
classifier call) decides whether the reply genuinely asks about
accessibility; when it doesn't, _retry_guided_field_question forces the
hint and asks Tinkerbell AGAIN (a real model re-ask, never a canned
sentence).

Run: python3 tools/qa_dryrun4_accessibility_asked_before_baggage.py
"""
import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import ariella_chat_clean as chat

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


STATE_ACCESSIBILITY_OPEN = {
    "guided": {"current_question": "accessibility", "answered": ["dates", "travelers"], "attempts": 0},
    "accessibility": None,
    "flight": {"baggage": []},
    "_guided_ask_hint": "הפרט הבא לברר: האם מישהו מהנוסעים צריך התאמות נגישות בחופשה.",
}

LIVE_SKIPPED_REPLY = "מצוין, אשאיר את זה כהעדפה.\n\nלגבי כבודה - איזו כבודה תצטרכו לקחת?"
RETRIED_REPLY = "יש מישהו מהנוסעים שצריך התאמות נגישות כלשהן בחופשה הזו?"


def _classifier(asked):
    def fake(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
        if source == "classifier":
            return json.dumps({"asked": asked})
        return "{}"
    return fake


# --- 1. Classifier says "not asked" -> forces a genuine retry via _call_tinkerbell ---
with patch.object(chat, "_post_claude", side_effect=_classifier(False)), \
        patch.object(chat, "_call_tinkerbell", return_value=RETRIED_REPLY) as mock_retry:
    result = chat._guard_accessibility_question_skipped(
        LIVE_SKIPPED_REPLY, STATE_ACCESSIBILITY_OPEN, "k", "m", [], "עדיף ישירה"
    )
check("finding 4 repro: a reply that skips accessibility (classifier says 'not asked') triggers a genuine retry",
      result == RETRIED_REPLY)
check("the retry goes through _call_tinkerbell with _guided_question_retry=True (never a fixed sentence)",
      mock_retry.call_args.kwargs.get("_guided_question_retry") is True)
check("the retry forces guided.current_question back to 'accessibility'",
      mock_retry.call_args[0][4].get("guided", {}).get("current_question") == "accessibility")

# --- 2. Classifier says "asked" -> reply passes through unchanged, no retry call ---
with patch.object(chat, "_post_claude", side_effect=_classifier(True)), \
        patch.object(chat, "_call_tinkerbell") as mock_no_retry:
    compliant = "יש מישהו מהנוסעים שצריך התאמות נגישות כלשהן בחופשה הזו? זה ממש לא חובה לענות."
    result2 = chat._guard_accessibility_question_skipped(compliant, STATE_ACCESSIBILITY_OPEN, "k", "m", [], "x")
check("regression: classifier confirms the reply genuinely asks -> passes through unchanged",
      result2 == compliant)
check("regression: no retry call made when the classifier says it was asked",
      not mock_no_retry.called)

# --- 3. Open follow-up stage (awaiting_detail) is never touched - no classifier call ---
STATE_AWAITING_DETAIL = {
    "guided": {"current_question": "accessibility", "answered": ["dates", "travelers"], "attempts": 0},
    "accessibility": {"asked": True, "needed": True},
    "flight": {"baggage": []},
}
with patch.object(chat, "_post_claude") as mock_classifier_unused:
    result3 = chat._guard_accessibility_question_skipped("משהו שלא קשור לנגישות בכלל?", STATE_AWAITING_DETAIL, "k", "m", [], "x")
check("regression: the open follow-up (awaiting_detail) stage is never touched, no classifier call",
      result3 == "משהו שלא קשור לנגישות בכלל?" and not mock_classifier_unused.called)

# --- 4. Already settled -> never touched, no classifier call ---
STATE_SETTLED = {
    "guided": {"current_question": "accessibility", "answered": ["dates", "travelers", "accessibility"], "attempts": 0},
    "accessibility": {"asked": True, "needed": False},
    "flight": {"baggage": []},
}
with patch.object(chat, "_post_claude") as mock_classifier_unused2:
    result4 = chat._guard_accessibility_question_skipped("לגבי כבודה - איזו כבודה תצטרכו לקחת?", STATE_SETTLED, "k", "m", [], "x")
check("regression: once accessibility is already settled, the guard never fires or calls the classifier",
      result4 == "לגבי כבודה - איזו כבודה תצטרכו לקחת?" and not mock_classifier_unused2.called)

# --- 5. current_question != 'accessibility' -> never touched, no classifier call ---
STATE_OTHER_FIELD = {"guided": {"current_question": "baggage"}, "accessibility": None, "flight": {"baggage": []}}
with patch.object(chat, "_post_claude") as mock_classifier_unused3:
    result5 = chat._guard_accessibility_question_skipped("איזו כבודה תצטרכו לקחת?", STATE_OTHER_FIELD, "k", "m", [], "x")
check("regression: current_question != 'accessibility' never triggers the guard or the classifier",
      result5 == "איזו כבודה תצטרכו לקחת?" and not mock_classifier_unused3.called)

# --- 6. Baggage already answered (backfill scenario) -> never fires, no classifier call ---
STATE_BAGGAGE_ALREADY_ANSWERED = {
    "guided": {"current_question": "accessibility", "answered": ["dates", "travelers", "baggage"], "attempts": 0},
    "accessibility": None,
    "flight": {"baggage": ["personal_item"]},
}
with patch.object(chat, "_post_claude") as mock_classifier_unused4:
    result6 = chat._guard_accessibility_question_skipped("מה התקציב שלכם לאדם לטיסה?", STATE_BAGGAGE_ALREADY_ANSWERED, "k", "m", [], "x")
check("regression: baggage already answered (backfill scenario) never triggers the guard or the classifier",
      result6 == "מה התקציב שלכם לאדם לטיסה?" and not mock_classifier_unused4.called)


print()
if FAILED:
    print(f"{len(FAILED)} CHECK(S) FAILED:")
    for name in FAILED:
        print(" -", name)
    sys.exit(1)
else:
    print("ALL DRYRUN4-ACCESSIBILITY-ASKED-BEFORE-BAGGAGE TESTS PASSED")
