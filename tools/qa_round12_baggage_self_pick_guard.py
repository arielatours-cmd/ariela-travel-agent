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

Fixed: _guard_baggage_type_self_picked (ariella_chat_clean.py), a
deterministic safety net wired into _call_tinkerbell's reply pipeline. When
current_question=="baggage" and flight.baggage is still unset, her reply's
own actual question (last clause before the final "?") must be about
baggage - if it isn't (she self-decided, or asked about something else
entirely), the canonical three-option question replaces the whole reply.

Run: python3 tools/qa_round12_baggage_self_pick_guard.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

from ariella_chat_clean import _guard_baggage_type_self_picked, _BAGGAGE_TYPE_QUESTION_FALLBACK

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


STATE_BAGGAGE_OPEN = {
    "guided": {"current_question": "baggage", "answered": ["dates", "travelers"], "mixed_baggage_pending": False},
    "flight": {"baggage": []},
    # The arbiter must actually pick the guided hint as this turn's winner
    # (see _turn_question_arbiter) - the guard only fires when nothing
    # higher-priority (a date shift, a gap-clarify doubt, a destination
    # gateway question) won instead.
    "_guided_ask_hint": "הפרט הבא לברר אצל הלקוח: איזו כבודה לוקחים.",
}

# The exact live reply (Zadar, round 12, finding E) - self-picked a type,
# never asked.
LIVE_SELF_PICKED_REPLY = (
    "אוקיי, אז כיוון ששתיים מכן צריכות מזוודה, הכי בטוח שכולכן תזמינו מזוודה "
    "בבטן המטוס - כך לא תהיה בעיה לאף אחת.\n\n"
    "ולגבי שדה התעופה - לזדאר אין שדה בינלאומי מסחרי ישיר, אז צריך לבחור דרך "
    "איזה שדה קרוב לנחות ולהמשיך משם. חשוב לכם שהטיסה תהיה ישירה?"
)
guarded = _guard_baggage_type_self_picked(LIVE_SELF_PICKED_REPLY, STATE_BAGGAGE_OPEN)
check(
    "finding E repro: a self-picked baggage type with no real baggage question is replaced",
    guarded == _BAGGAGE_TYPE_QUESTION_FALLBACK,
)

# A compliant reply (asks the real baggage question) must pass through untouched.
COMPLIANT_REPLY = (
    'בסדר גמור. אז בשלב ההזמנה אפשר לבחור סוג כבודה אחד לכל הקבוצה - '
    'איזו כבודה לוקחים: תיק יד בלבד, טרולי, או מזוודה בבטן המטוס?'
)
check(
    "regression: a reply that genuinely asks about baggage type passes through unchanged",
    _guard_baggage_type_self_picked(COMPLIANT_REPLY, STATE_BAGGAGE_OPEN) == COMPLIANT_REPLY,
)

# Once flight.baggage is actually saved, the guard must never touch the reply
# (e.g. a later turn, baggage already resolved, talking about something else).
STATE_BAGGAGE_SAVED = {
    "guided": {"current_question": "baggage", "answered": ["dates", "travelers", "baggage"]},
    "flight": {"baggage": ["checked_bag"]},
}
check(
    "regression: once flight.baggage is saved, the guard never overrides the reply",
    _guard_baggage_type_self_picked("נשמר מעולה, מה לגבי התקציב לאדם?", STATE_BAGGAGE_SAVED) == "נשמר מעולה, מה לגבי התקציב לאדם?",
)

# When current_question isn't "baggage" at all, the guard must never fire,
# regardless of reply content.
STATE_OTHER_FIELD = {"guided": {"current_question": "accessibility"}, "flight": {"baggage": []}}
check(
    "regression: current_question != 'baggage' never triggers the guard",
    _guard_baggage_type_self_picked("משהו שלא קשור לכבודה בכלל - תקציב לאדם?", STATE_OTHER_FIELD)
    == "משהו שלא קשור לכבודה בכלל - תקציב לאדם?",
)


print()
if FAILED:
    print(f"{len(FAILED)} CHECK(S) FAILED:")
    for name in FAILED:
        print(" -", name)
    sys.exit(1)
else:
    print("ALL ROUND12-BAGGAGE-SELF-PICK-GUARD TESTS PASSED")
