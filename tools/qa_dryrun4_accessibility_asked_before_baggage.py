"""QA for dry-run 4 finding 4 (Shaked/Shlomo, 22.10.2026, qa-dryrun branch,
qa/dryrun/2026-10-22-dr4-ABCEF/dr4_F.log, Prague):

Real transcript: guided.current_question was "accessibility" (dates and
travelers both already answered from the opening message), and the
dynamic_hint correctly told Tinkerbell to ask the accessibility yes/no.
Instead, her free text skipped straight to baggage ("לגבי כבודה - איזו
כבודה תצטרכו לקחת?") - no accessibility question anywhere in the reply.
_guided_redirect_field's existing safety net recovered the baggage answer
correctly on the next turn (nothing was lost from state), and accessibility
was asked correctly one turn late - but the customer still experienced
baggage asked BEFORE accessibility, the wrong order the guided flow exists
to guarantee.

Fixed: _guard_accessibility_question_skipped (ariella_chat_clean.py), a
deterministic safety net in _call_tinkerbell's reply pipeline. When
current_question=="accessibility" and it isn't settled yet (and we're on
the yes/no stage, not the open detail follow-up), the reply's own actual
question must mention accessibility/accommodation wording - if it doesn't,
the canonical yes/no question replaces the whole reply.

Run: python3 tools/qa_dryrun4_accessibility_asked_before_baggage.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

from ariella_chat_clean import _guard_accessibility_question_skipped, _ACCESSIBILITY_YES_NO_FALLBACK

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
    # The arbiter must actually pick the guided hint as this turn's winner
    # (see _turn_question_arbiter) - the guard only fires when nothing
    # higher-priority (a date shift, a gap-clarify doubt, a destination
    # gateway question) won instead.
    "_guided_ask_hint": "הפרט הבא לברר: האם מישהו מהנוסעים צריך התאמות נגישות בחופשה.",
}

# The exact live reply (Prague, dry-run 4, finding 4, scenario F) - skipped
# straight to baggage.
LIVE_SKIPPED_REPLY = "מצוין, אשאיר את זה כהעדפה.\n\nלגבי כבודה - איזו כבודה תצטרכו לקחת?"
guarded = _guard_accessibility_question_skipped(LIVE_SKIPPED_REPLY, STATE_ACCESSIBILITY_OPEN)
check(
    "finding 4 repro: a reply that skips accessibility for baggage is replaced with the real question",
    guarded == _ACCESSIBILITY_YES_NO_FALLBACK,
)

# A compliant reply (genuinely asks about accessibility) passes through unchanged.
COMPLIANT_REPLY = "יש מישהו מהנוסעים שצריך התאמות נגישות כלשהן בחופשה הזו? זה ממש לא חובה לענות."
check(
    "regression: a reply that genuinely asks about accessibility passes through unchanged",
    _guard_accessibility_question_skipped(COMPLIANT_REPLY, STATE_ACCESSIBILITY_OPEN) == COMPLIANT_REPLY,
)

# On the OPEN FOLLOW-UP stage (awaiting_detail), the guard must never fire -
# there is no single fixed question to fall back to there.
STATE_AWAITING_DETAIL = {
    "guided": {"current_question": "accessibility", "answered": ["dates", "travelers"], "attempts": 0},
    "accessibility": {"asked": True, "needed": True},
    "flight": {"baggage": []},
}
check(
    "regression: the open follow-up (awaiting_detail) stage is never touched by this guard",
    _guard_accessibility_question_skipped("משהו שלא קשור לנגישות בכלל?", STATE_AWAITING_DETAIL)
    == "משהו שלא קשור לנגישות בכלל?",
)

# Once accessibility is already settled (known_with_confidence), the guard
# must never fire even if current_question is stale.
STATE_SETTLED = {
    "guided": {"current_question": "accessibility", "answered": ["dates", "travelers", "accessibility"], "attempts": 0},
    "accessibility": {"asked": True, "needed": False},
    "flight": {"baggage": []},
}
check(
    "regression: once accessibility is already settled, the guard never overrides the reply",
    _guard_accessibility_question_skipped("לגבי כבודה - איזו כבודה תצטרכו לקחת?", STATE_SETTLED)
    == "לגבי כבודה - איזו כבודה תצטרכו לקחת?",
)

# current_question != "accessibility" never triggers the guard.
STATE_OTHER_FIELD = {"guided": {"current_question": "baggage"}, "accessibility": None, "flight": {"baggage": []}}
check(
    "regression: current_question != 'accessibility' never triggers the guard",
    _guard_accessibility_question_skipped("איזו כבודה תצטרכו לקחת?", STATE_OTHER_FIELD)
    == "איזו כבודה תצטרכו לקחת?",
)


print()
if FAILED:
    print(f"{len(FAILED)} CHECK(S) FAILED:")
    for name in FAILED:
        print(" -", name)
    sys.exit(1)
else:
    print("ALL DRYRUN4-ACCESSIBILITY-ASKED-BEFORE-BAGGAGE TESTS PASSED")
