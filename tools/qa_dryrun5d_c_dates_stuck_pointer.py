"""QA for dry-run 5d finding C (Shaked, 23.10.2026, Hallstatt/Salzburg;
qa/reports/2026-10-23-dryrun5d.md): guided.current_question stayed stuck
on "dates" for the rest of the conversation after the customer chose one
of two pre-offered candidate date ranges ("האפשרות הראשונה") in turn 1 -
dates.departure/return were already concrete and needs_confirmation
already False from turn 1 onward, but nothing ever moved the pointer off
"dates" (that resolution happens through a SEPARATE deterministic path,
_deterministic_candidate_choice_facts, never through this guided
extraction branch itself - unlike accessibility, which always advances
its own pointer once answered). The live result: 5 repeated "when
exactly do you want to leave" questions through turn 9, when the
customer's plain "כן" (nothing new) was still extracted against dates
as if never answered.

Shlomo's explicit approval (23.10.2026) - a narrowly-scoped fix, NOT the
broad "field in answered" generalization that broke 4 existing tests
when tried before (see the 22.10 commit 4fbe81ec, scoped to accessibility
only for the same reason): the pointer moves off "dates" only when
dates.needs_confirmation is False AND both departure/return are concrete
- never travelers/baggage/lodging, which keep their pointer on purpose
for their own correction flow. His acceptance criteria:
  (a) the 4 existing tests that failed in the earlier generalization
      attempt still pass (covered by the full QA sweep, not just this
      file - this fix never touches the generic "field in answered"
      path those 4 relied on).
  (b) a test reproducing C from 5d (choosing "the first option", then a
      later plain "כן") that never re-asks about dates.
  (c) full QA green.

Offline (the guided extraction model call is stubbed). Run:
python3 tools/qa_dryrun5d_c_dates_stuck_pointer.py
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


STEPS = {"dates", "travelers", "accessibility", "baggage"}
RESOLVED_DATES = {"departure": "2026-11-21", "return": "2026-11-25",
                   "needs_confirmation": False, "candidate_ranges": []}
PENDING_DATES = {"departure": None, "return": None, "needs_confirmation": True,
                  "candidate_ranges": ["18.4.2027–22.4.2027", "25.4.2027–29.4.2027"]}


def c_state(guided_extra=None, dates=None, other_fields_answered=False):
    g = {"current_question": "dates", "attempts": 0, "answered": []}
    g.update(guided_extra or {})
    state = {
        "requested_services": ["flights"],
        "travelers": {"adults": 2} if other_fields_answered else {},
        "dates": dict(dates if dates is not None else RESOLVED_DATES),
        "accessibility": {"needed": False} if other_fields_answered else {},
        "flight": {"baggage": ["carry_on_only"] if other_fields_answered else [], "connection_preference": "אין העדפה"},
        "guided": g,
    }
    if other_fields_answered:
        state["guided"]["answered"] = list(set(state["guided"].get("answered") or []) | {"travelers", "accessibility", "baggage"})
    return state


def run(state, message):
    asked = []

    def fake_extract(key, model, field, msg, history, s, guided_steps=None):
        asked.append(field)
        return {"status": "other_topic", "confidence": "low", "also_mentioned": {}, "correction": None}

    with patch.object(chat, "_guided_extract_answer", side_effect=fake_extract), \
            patch.object(chat, "_guided_redirect_field", return_value=None), \
            patch.object(chat, "record_diagnostic_event"):
        result = chat._handle_guided_extraction_turn("k", "m", message, [], state, dict(state), STEPS)
    return (result or {"trip_update": dict(state), "dynamic_hint": None}), asked


# =====================================================================
# Part 1: turn 1 - the moment dates resolves via the deterministic
# candidate-choice path (trip_update already carries the resolved dates,
# as it would after that separate pipeline step earlier in the real
# per-turn handler), with current_question still "dates" from the very
# start of the guided flow. The fix must move the pointer off dates
# immediately - the SAME turn, never waiting for a later one.
# =====================================================================
r1, asked1 = run(c_state(), "האפשרות הראשונה")
check("turn 1 FIX: dates is never re-extracted the same turn it resolved "
      "via the deterministic candidate-choice path",
      "dates" not in asked1)
check("turn 1 FIX: 'dates' is recorded in guided.answered immediately",
      "dates" in r1["trip_update"]["guided"]["answered"])
check("turn 1 FIX: the pointer moves on to the next genuinely open field (travelers)",
      r1["trip_update"]["guided"]["current_question"] == "travelers")
check("turn 1 FIX: travelers IS extracted this same turn (the pointer actually "
      "advanced and ran, not just flipped to None)",
      asked1 == ["travelers"])


# =====================================================================
# Part 2 (Shlomo's criterion b - the exact C repro): turn 9 - every other
# guided field already answered in the meantime, current_question STILL
# shows "dates" (the pre-fix bug state), customer sends a plain "כן" with
# nothing new. The fix must never re-ask about dates - nothing is left
# to guide at all once dates's own pointer is corrected, so the function
# reports "nothing to do" instead of extracting against dates again.
# =====================================================================
turn9_state = c_state(other_fields_answered=True)
r9, asked9 = run(turn9_state, "כן")
check("C repro (criterion b) FIX: 'כן' (nothing new) at turn 9 is NEVER extracted "
      "against the stale dates pointer",
      "dates" not in asked9)
check("C repro (criterion b) FIX: no dates-related dynamic_hint is produced this turn "
      "(nothing left to guide - every field, dates included, is genuinely answered)",
      not r9.get("dynamic_hint") or "תאריכ" not in (r9.get("dynamic_hint") or ""))
check("C repro (criterion b) FIX: current_question is cleared, not left stuck on 'dates'",
      (r9["trip_update"].get("guided") or {}).get("current_question") != "dates")


# =====================================================================
# Part 3: regression guard - while dates is still genuinely PENDING a
# candidate choice (needs_confirmation True, no concrete departure/
# return yet), the pointer must stay on "dates" exactly as before - the
# fix never fires on a provisional, unconfirmed date.
# =====================================================================
pending_state = c_state(dates=PENDING_DATES)
r_pending, asked_pending = run(pending_state, "18 עד 22")
check("regression: a still-pending (needs_confirmation True) dates candidate choice "
      "keeps the pointer live on dates - extraction still runs against it",
      asked_pending == ["dates"])
check("regression: 'dates' is NOT prematurely marked answered while still pending",
      "dates" not in r_pending["trip_update"]["guided"]["answered"])


# =====================================================================
# Part 4: regression guard - the fix is scoped to current_question=="dates"
# only; a stale pointer on a DIFFERENT field is never touched by this new
# block (travelers/baggage/lodging deliberately keep their pointer on an
# answered field on purpose, per the standing 22.10 decision this fix
# does not revisit).
# =====================================================================
travelers_state = c_state(guided_extra={"current_question": "travelers", "answered": ["dates"]})
travelers_state["travelers"] = {"adults": 2}  # already known, but pointer deliberately left here
r_trav, asked_trav = run(travelers_state, "משהו לא קשור")
check("regression: a stale pointer on travelers (not dates) is untouched by this fix - "
      "still extracted against travelers as before",
      asked_trav == ["travelers"])


if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DRYRUN5D-C-DATES-STUCK-POINTER TESTS PASSED")
