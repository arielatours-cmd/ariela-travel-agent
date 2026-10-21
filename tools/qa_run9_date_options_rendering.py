"""QA for Shlomo's run-9 Timișoara finding (21.10.2026, relayed after the
run-9 diagnostics PR #123 merged, per his explicit sequencing - "קודם
האבחון, והממצא הזה אחריו"):

"ב-state היו 2 אפשרויות, ואריאלה הציגה רק אחת, כשאלת כן/לא: 'סביב ה-11-15
בנובמבר?'. לבדוק: האם {{DATE_OPTIONS}} רונדר."

Root cause confirmed by direct code reading: _render_date_placeholders
itself renders {{DATE_OPTIONS}} correctly when Tinkerbell actually writes
it - every pending dates.candidate_ranges entry gets joined with " או "
(see its own _resolve("DATE_OPTIONS") branch). The real gap is upstream:
nothing ever enforced that she uses the placeholder in the first place.
_retry_if_dates_invented's own structural backstop never catches this
shape either - the date she names ("11-15 בנובמבר") IS one of the two
real pending candidates, not an invented or mixed one, so it passes that
check cleanly. The actual bug is which candidate(s) she silently left out
of the reply, never what she said.

Fix: a new structural backstop, _retry_if_one_of_several_candidates_shown,
alongside _retry_if_dates_invented - when state has 2+ pending candidates,
the raw reply never contained the {{DATE_OPTIONS}} token at all, and the
reply names EXACTLY ONE candidate's own whole range, it is retried once
with a hint to show every pending option via the placeholder instead of
picking one herself. Naming zero candidates (an ordinary clarifying
question) or two-or-more (she already listed more than one, just without
the placeholder) is left alone - only the "silently picked one of several"
shape is structurally wrong.

Run: python3 tools/qa_run9_date_options_rendering.py
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

TWO_CANDIDATES_STATE = {
    "active_session": "flights",
    "dates": {
        "departure": None, "return": None, "needs_confirmation": True,
        "candidate_ranges": [
            "יום שלישי 11.11.2026–יום שבת 15.11.2026",
            "יום שלישי 18.11.2026–יום שבת 22.11.2026",
        ],
    },
}


def _fake_retry_reply_factory(text):
    def _fake(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
        return text
    return _fake


# =====================================================================
# Direct unit coverage of the new backstop itself.
# =====================================================================
with patch.object(chat, "_post_claude", side_effect=_fake_retry_reply_factory(
    "בטח, שתי האפשרויות הן " + chat._DATE_OPTIONS_PLACEHOLDER
)):
    _result_timisoara = chat._retry_if_one_of_several_candidates_shown(
        KEY, MODEL, [], "מתי אפשר לטוס?", TWO_CANDIDATES_STATE,
        "אולי סביב ה-11-15 בנובמבר?", False,
    )
check("Timișoara repro: naming exactly one of two pending candidates (no {{DATE_OPTIONS}} "
      "token in the raw reply) triggers a retry",
      _result_timisoara is not None)
check("Timișoara repro: the retried reply now shows BOTH pending candidates joined by 'או' "
      "(the placeholder actually got used and rendered this time)",
      _result_timisoara is not None
      and "11.11.2026" in _result_timisoara and "18.11.2026" in _result_timisoara
      and " או " in _result_timisoara)

# Regression: only ONE pending candidate - nothing to silently leave out.
ONE_CANDIDATE_STATE = dict(TWO_CANDIDATES_STATE, dates=dict(
    TWO_CANDIDATES_STATE["dates"], candidate_ranges=["יום שלישי 11.11.2026–יום שבת 15.11.2026"],
))
check("regression: a single pending candidate never triggers this backstop "
      "(nothing was left out - there was only ever one option)",
      chat._retry_if_one_of_several_candidates_shown(
          KEY, MODEL, [], "מתי אפשר לטוס?", ONE_CANDIDATE_STATE,
          "אולי סביב ה-11-15 בנובמבר?", False,
      ) is None)

# Regression: a plain clarifying question naming no date at all.
check("regression: a reply naming no date-shaped range at all (an ordinary "
      "clarifying question) never triggers this backstop",
      chat._retry_if_one_of_several_candidates_shown(
          KEY, MODEL, [], "מתי אפשר לטוס?", TWO_CANDIDATES_STATE,
          "איזה טווח תאריכים הכי מתאים לכם?", False,
      ) is None)

# Regression: BOTH candidates named explicitly (no placeholder, but nothing
# was actually left out this time).
check("regression: a reply that already names BOTH pending candidates itself "
      "(just without the placeholder) never triggers this backstop",
      chat._retry_if_one_of_several_candidates_shown(
          KEY, MODEL, [], "מתי אפשר לטוס?", TWO_CANDIDATES_STATE,
          "אפשר 11-15 בנובמבר או 18-22 בנובמבר - מה מתאים?", False,
      ) is None)

# Regression: had_date_options_token=True short-circuits regardless of what
# the (already-substituted) text happens to read now.
check("regression: had_date_options_token=True short-circuits the whole check "
      "(the raw reply used the placeholder, which already joins every candidate)",
      chat._retry_if_one_of_several_candidates_shown(
          KEY, MODEL, [], "מתי אפשר לטוס?", TWO_CANDIDATES_STATE,
          "אולי סביב ה-11-15 בנובמבר?", True,
      ) is None)

# Regression: dates already confirmed (not pending) - not this backstop's job.
CONFIRMED_STATE = {
    "active_session": "flights",
    "dates": {"departure": "2026-11-11", "return": "2026-11-15", "needs_confirmation": False, "candidate_ranges": []},
}
check("regression: dates already confirmed (needs_confirmation=False) never triggers this backstop",
      chat._retry_if_one_of_several_candidates_shown(
          KEY, MODEL, [], "מתי אפשר לטוס?", CONFIRMED_STATE,
          "אולי סביב ה-11-15 בנובמבר?", False,
      ) is None)

# Regression: outside the flights stage (e.g. trip_planning/itinerary text
# legitimately names many real per-day dates).
PLANNING_STATE = dict(TWO_CANDIDATES_STATE, active_session="trip_planning")
check("regression: scoped to the flights stage only, same as the sibling date backstops",
      chat._retry_if_one_of_several_candidates_shown(
          KEY, MODEL, [], "מתי אפשר לטוס?", PLANNING_STATE,
          "אולי סביב ה-11-15 בנובמבר?", False,
      ) is None)


# =====================================================================
# End-to-end: a real _call_tinkerbell turn where the first reply picks
# just one of two pending candidates as a yes/no, and the retry call
# (mocked to behave correctly this time) uses the placeholder.
# =====================================================================
_calls = {"n": 0}


def _fake_end_to_end(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    _calls["n"] += 1
    if _calls["n"] == 1:
        return "אולי סביב ה-11-15 בנובמבר?"
    return "בטח, שתי האפשרויות הן " + chat._DATE_OPTIONS_PLACEHOLDER


with patch.object(chat, "_post_claude", side_effect=_fake_end_to_end):
    _final = chat._call_tinkerbell(KEY, MODEL, [], "מתי אפשר לטוס?", dict(TWO_CANDIDATES_STATE))
check("end-to-end: _call_tinkerbell's own first-reply-picks-one-candidate shape gets "
      "retried automatically, landing on a reply with both candidates shown",
      "11.11.2026" in _final and "18.11.2026" in _final and " או " in _final)
check("end-to-end: exactly one retry happened (two total _post_claude calls for the reply itself)",
      _calls["n"] == 2)


if FAILED:
    print(f"\n{len(FAILED)} CHECK(S) FAILED:")
    for name in FAILED:
        print(f"  - {name}")
    sys.exit(1)
print("\nALL RUN-9 DATE-OPTIONS-RENDERING TESTS PASSED")
