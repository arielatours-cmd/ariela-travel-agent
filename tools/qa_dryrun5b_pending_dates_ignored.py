"""QA for dry-run 5b item 5 (Shlomo/Shaked, 22.10.2026, qa-dryrun branch,
qa/dryrun/2026-10-22-dr5-typos/dr5_C.log, Hallstatt/Salzburg):

Turn 1: "זוג להלשטאט בסוף החודש הבא, לחמישה ימים" (end of next month, for
5 days) - correctly understood and turned into two real candidate date
ranges (dates.candidate_ranges, needs_confirmation=True) that SAME turn,
but the turn's own reply was about the destination gateway question
instead (destination_airports still unresolved, the higher-priority
unresolved fact that turn). Turn 2: "זלצבורד מתאים לנו" resolves the
gateway (destination_airports becomes SZG, confirmed as a fact, no
question needed) - dates genuinely becomes the live question this turn
(guided.current_question == "dates", nothing higher-priority competing)
- yet Tinkerbell's reply asked a completely fresh "מתי בערך תרצה לצאת?"
as if the customer had never said anything about dates at all, ignoring
the real pending candidates already sitting in state and _dates_truth_
hint's own standing instruction to present them via {{DATE_OPTIONS}}.

Root cause: neither existing date backstop catches this shape.
_retry_if_dates_invented only fires on an invented/mismatched date
actually WRITTEN in the reply (there is none here). _retry_if_one_of_
several_candidates_shown only fires when exactly ONE real candidate is
named without the placeholder (she named zero - not even a partial
mention). This is the missing third shape: the placeholder is absent AND
not a single candidate range (or any date-shaped token) is mentioned
either - a genuine skip, not a format slip in an otherwise-engaged reply.

Fixed: a new structural backstop, _retry_if_pending_dates_ignored,
alongside the other two - fires only when dates is genuinely this turn's
winning topic (guided.current_question == "dates" and _turn_question_
arbiter's own winning kind is "guided" - never when some other higher-
priority hint legitimately won the turn instead, where not mentioning
dates at all is correct, not a skip), dates.needs_confirmation is True
with real candidate_ranges, the raw reply never used {{DATE_OPTIONS}},
and the reply mentions zero date-shaped tokens of any kind.

Run: python3 tools/qa_dryrun5b_pending_dates_ignored.py
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

import ariella_chat_clean as chat

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


KEY = os.getenv("ANTHROPIC_API_KEY", "test-key-not-real")
MODEL = "claude-sonnet-5"

PENDING_DATES_STATE = {
    "active_session": "flights",
    "dates": {
        "departure": None, "return": None, "needs_confirmation": True,
        "candidate_ranges": [
            "יום שבת 21.11.2026–יום רביעי 25.11.2026",
            "יום חמישי 26.11.2026–יום שני 30.11.2026",
        ],
    },
    "guided": {"current_question": "dates", "attempts": 0, "answered": ["travelers"]},
    "_guided_ask_hint": "הפרט הבא לברר אצל הלקוח: תאריכי היציאה והחזרה המבוקשים. שאלי שאלה אחת ויחידה על כך, פתוחה.",
}


def _fake_retry_reply_factory(text):
    def _fake(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
        return text
    return _fake


# =====================================================================
# Direct unit coverage of the new backstop itself.
# =====================================================================
with patch.object(chat, "_post_claude", side_effect=_fake_retry_reply_factory(
    "בטח, האפשרויות הן " + chat._DATE_OPTIONS_PLACEHOLDER
)):
    _result = chat._retry_if_pending_dates_ignored(
        KEY, MODEL, [], "זלצבורד מתאים לנו", PENDING_DATES_STATE,
        "מצוין, זלצבורג זה בדיוק השדה הקרוב להלשטאט. מתי בערך תרצה לצאת לטיול?", False,
    )
check("scenario C repro: a totally fresh open dates question, with real pending "
      "candidates in state and dates genuinely the live topic, triggers a retry",
      _result is not None)
check("scenario C repro: the retried reply shows the real pending candidates "
      "(the placeholder actually got used and rendered this time)",
      _result is not None and "21.11.2026" in _result and "26.11.2026" in _result and " או " in _result)

# Regression: had_date_options_token=True short-circuits regardless of text.
check("regression: had_date_options_token=True short-circuits the whole check",
      chat._retry_if_pending_dates_ignored(
          KEY, MODEL, [], "זלצבורד מתאים לנו", PENDING_DATES_STATE,
          "מתי בערך תרצה לצאת לטיול?", True,
      ) is None)

# Regression: dates already confirmed (not pending) - not this backstop's job.
CONFIRMED_STATE = dict(PENDING_DATES_STATE, dates={
    "departure": "2026-11-21", "return": "2026-11-25", "needs_confirmation": False, "candidate_ranges": [],
})
check("regression: dates already confirmed (needs_confirmation=False) never triggers this backstop",
      chat._retry_if_pending_dates_ignored(
          KEY, MODEL, [], "זלצבורד מתאים לנו", CONFIRMED_STATE,
          "מתי בערך תרצה לצאת לטיול?", False,
      ) is None)

# Regression: dates is NOT the live topic this turn (something else is, e.g.
# the destination-gateway question is still unresolved and wins instead) -
# never asking about dates at all is correct here, not a skip.
_state_gateway_wins = dict(PENDING_DATES_STATE)
_state_gateway_wins["destination"] = {"places": ["הלשטאט"], "mode": "specific", "status": "known"}
_state_gateway_wins["destination_airports"] = []
_state_gateway_wins["requested_services"] = ["flights"]
_state_gateway_wins["service_decisions"] = {"flights": {"wanted": True}}
check("regression: a genuinely higher-priority competing hint (destination gateway still "
      "unresolved) winning the turn instead means this backstop never fires",
      chat._retry_if_pending_dates_ignored(
          KEY, MODEL, [], "זלצבורד מתאים לנו", _state_gateway_wins,
          "לאיזה שדה תעופה הכי נוח לך לטוס ולנחות?", False,
      ) is None)

# Regression: guided.current_question isn't "dates" at all (e.g. accessibility
# is the live field) - this backstop is scoped to dates specifically.
_state_accessibility_live = dict(PENDING_DATES_STATE, guided={
    "current_question": "accessibility", "attempts": 0, "answered": ["dates", "travelers"],
})
check("regression: guided.current_question isn't 'dates' - never this backstop's job",
      chat._retry_if_pending_dates_ignored(
          KEY, MODEL, [], "לא צריך התאמות", _state_accessibility_live,
          "בסדר גמור. מה התקציב שלכם לאדם לטיסה?", False,
      ) is None)

# Regression: a reply that DOES mention a pending candidate (even without the
# placeholder) is the sibling backstop's job, not this one.
check("regression: the reply already mentions one of the real pending candidates - "
      "not a total skip, left to _retry_if_one_of_several_candidates_shown instead",
      chat._retry_if_pending_dates_ignored(
          KEY, MODEL, [], "זלצבורד מתאים לנו", PENDING_DATES_STATE,
          "אולי סביב ה-21-25 בנובמבר?", False,
      ) is None)

# Regression: outside the flights stage.
PLANNING_STATE = dict(PENDING_DATES_STATE, active_session="trip_planning")
check("regression: scoped to the flights stage only, same as the sibling date backstops",
      chat._retry_if_pending_dates_ignored(
          KEY, MODEL, [], "זלצבורד מתאים לנו", PLANNING_STATE,
          "מתי בערך תרצה לצאת לטיול?", False,
      ) is None)

# Regression: no pending candidates at all.
NO_CANDIDATES_STATE = dict(PENDING_DATES_STATE, dates={
    "departure": None, "return": None, "needs_confirmation": False, "candidate_ranges": [],
})
check("regression: no pending candidate_ranges at all - nothing to have ignored",
      chat._retry_if_pending_dates_ignored(
          KEY, MODEL, [], "זלצבורד מתאים לנו", NO_CANDIDATES_STATE,
          "מתי בערך תרצה לצאת לטיול?", False,
      ) is None)


# =====================================================================
# End-to-end: a real _call_tinkerbell turn reproducing the exact dr5b
# scenario C shape - the first reply ignores pending dates entirely, the
# retry (mocked to behave correctly this time) uses the placeholder.
# =====================================================================
_calls = {"n": 0}


def _fake_end_to_end(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    _calls["n"] += 1
    if _calls["n"] == 1:
        return "מצוין, זלצבורג זה בדיוק השדה הקרוב להלשטאט. מתי בערך תרצה לצאת לטיול?"
    return "בטח, האפשרויות הן " + chat._DATE_OPTIONS_PLACEHOLDER


with patch.object(chat, "_post_claude", side_effect=_fake_end_to_end):
    _final = chat._call_tinkerbell(KEY, MODEL, [], "זלצבורד מתאים לנו", dict(PENDING_DATES_STATE))
check("end-to-end: _call_tinkerbell's own total-skip shape gets retried automatically, "
      "landing on a reply with the real pending candidates shown",
      "21.11.2026" in _final and "26.11.2026" in _final and " או " in _final)
check("end-to-end: exactly one retry happened (two total _post_claude calls for the reply itself)",
      _calls["n"] == 2)


if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DRYRUN5B-PENDING-DATES-IGNORED TESTS PASSED")
