"""QA for round-12 live finding E, part 1 (Shlomo/Shaked, 22.10.2026,
qa-dryrun branch "shaked", qa/live/2026-10-22-run12/r12_E.log):

Real transcript (Zadar, 3 travelers, 2 need a suitcase): Tinkerbell asked
"רוצה שנבחר כבודה אחידה לכולכן כרגע?" (uniform baggage for all of you?).
The customer answered "כן" - no type of her own named. Instead of then
asking the real follow-up question (the three options, per
_guided_ask_hint("baggage", 0)), Tinkerbell picked a type herself from
majority-need reasoning ("אוקיי, אז כיוון ששתיים מכן צריכות מזוודה, הכי
בטוח שכולכן תזמינו מזוודה בבטן המטוס") and never actually asked at all.
state itself stayed correct (flight.baggage was never silently saved) -
this is a pure drafting-compliance failure: Tinkerbell didn't follow the
hint she was given.

REWORKED per Shaked's review of the first version (round 12, e033a3b):
the original fix scanned the reply for marker words ("כבודה"/"מזוודה"/
"טרולי"/"תיק") and substituted a fixed fallback sentence when they were
missing - exactly the "no phrase lists on model output, no fixed
sentences replacing the model's answer" pattern the business owner
forbids. Fixed: _guided_question_actually_asked (a short model classifier
call, not a word scan) decides whether the reply genuinely asks about
baggage type; when it doesn't, _retry_guided_field_question forces the
hint and asks Tinkerbell AGAIN (a real model re-ask, never a canned
sentence).

Run: python3 tools/qa_round12_baggage_self_pick_guard.py
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


STATE_BAGGAGE_OPEN = {
    "guided": {"current_question": "baggage", "answered": ["dates", "travelers"], "mixed_baggage_pending": False},
    "flight": {"baggage": []},
    "_guided_ask_hint": "הפרט הבא לברר אצל הלקוח: איזו כבודה לוקחים.",
}

LIVE_SELF_PICKED_REPLY = (
    "אוקיי, אז כיוון ששתיים מכן צריכות מזוודה, הכי בטוח שכולכן תזמינו מזוודה "
    "בבטן המטוס - כך לא תהיה בעיה לאף אחת."
)
RETRIED_REPLY = "בסדר גמור - איזו כבודה תרצו לקחת לטיסה?"


def _classifier(asked):
    def fake(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
        if source == "classifier":
            return json.dumps({"asked": asked})
        return "{}"
    return fake


# --- 1. Classifier says "not asked" -> forces a genuine retry via _call_tinkerbell ---
with patch.object(chat, "_post_claude", side_effect=_classifier(False)), \
        patch.object(chat, "_call_tinkerbell", return_value=RETRIED_REPLY) as mock_retry:
    result = chat._guard_baggage_type_self_picked(
        LIVE_SELF_PICKED_REPLY, STATE_BAGGAGE_OPEN, "k", "m", [], "כן"
    )
check("finding E repro: a self-picked baggage type (classifier says 'not asked') triggers a genuine retry",
      result == RETRIED_REPLY)
check("the retry goes through _call_tinkerbell with _guided_question_retry=True (never a fixed sentence)",
      mock_retry.call_args.kwargs.get("_guided_question_retry") is True)
check("the retry forces guided.current_question back to 'baggage'",
      mock_retry.call_args[0][4].get("guided", {}).get("current_question") == "baggage")

# --- 2. Classifier says "asked" -> reply passes through unchanged, no retry call ---
with patch.object(chat, "_post_claude", side_effect=_classifier(True)), \
        patch.object(chat, "_call_tinkerbell") as mock_no_retry:
    compliant = "בסדר גמור. אז בשלב ההזמנה אפשר לבחור סוג כבודה אחד - איזו כבודה לוקחים: תיק יד בלבד, טרולי, או מזוודה?"
    result2 = chat._guard_baggage_type_self_picked(compliant, STATE_BAGGAGE_OPEN, "k", "m", [], "כן")
check("regression: classifier confirms the reply genuinely asks -> passes through unchanged",
      result2 == compliant)
check("regression: no retry call made when the classifier says it was asked",
      not mock_no_retry.called)

# --- 3. Once flight.baggage is actually saved, the guard never even calls the classifier ---
STATE_BAGGAGE_SAVED = {
    "guided": {"current_question": "baggage", "answered": ["dates", "travelers", "baggage"]},
    "flight": {"baggage": ["checked_bag"]},
}
with patch.object(chat, "_post_claude") as mock_classifier_unused:
    result3 = chat._guard_baggage_type_self_picked("נשמר מעולה, מה לגבי התקציב לאדם?", STATE_BAGGAGE_SAVED, "k", "m", [], "x")
check("regression: once flight.baggage is saved, the guard never calls the classifier at all",
      result3 == "נשמר מעולה, מה לגבי התקציב לאדם?" and not mock_classifier_unused.called)

# --- 4. current_question isn't 'baggage' -> never touched, no classifier call ---
STATE_OTHER_FIELD = {"guided": {"current_question": "accessibility"}, "flight": {"baggage": []}}
with patch.object(chat, "_post_claude") as mock_classifier_unused2:
    result4 = chat._guard_baggage_type_self_picked("משהו שלא קשור לכבודה בכלל", STATE_OTHER_FIELD, "k", "m", [], "x")
check("regression: current_question != 'baggage' never triggers the guard or the classifier",
      result4 == "משהו שלא קשור לכבודה בכלל" and not mock_classifier_unused2.called)

# --- 5. A pending date candidate / fact hint skips the guard without any classifier call ---
STATE_DATES_PENDING = {
    "guided": {"current_question": "baggage"},
    "flight": {"baggage": []},
    "dates": {"departure": "2026-11-17", "return": "2026-11-24", "needs_confirmation": True,
              "candidate_ranges": ["יום שלישי 20.11.2026–יום שלישי 27.11.2026"]},
}
with patch.object(chat, "_post_claude") as mock_classifier_unused3:
    result5 = chat._guard_baggage_type_self_picked("סגרנו את הכבודה - ולגבי התאריכים, 20.11–27.11 מתאים?", STATE_DATES_PENDING, "k", "m", [], "x")
check("regression: a standing pending date candidate skips the guard, no classifier call, no state scanning of the reply",
      result5 == "סגרנו את הכבודה - ולגבי התאריכים, 20.11–27.11 מתאים?" and not mock_classifier_unused3.called)


print()
if FAILED:
    print(f"{len(FAILED)} CHECK(S) FAILED:")
    for name in FAILED:
        print(" -", name)
    sys.exit(1)
else:
    print("ALL ROUND12-BAGGAGE-SELF-PICK-GUARD TESTS PASSED")
