"""QA for round-12 live finding E, remaining parts (Shlomo/Shaked,
22.10.2026, qa-dryrun branch "shaked", qa/live/2026-10-22-run12/r12_E.log,
Zadar):

Part 1 - internal reasoning leak: the live reply "מעולה, אז נהיה גמישים גם
לקונקשן.\n\n (למשל יש שדות אזוריים שונים שיכולים לשרת את האזור) לתכנן גם
מסלול ואטרקציות לחופשה הזו?" has a dangling example aside - "(למשל ...)" -
sitting directly in front of a completely unrelated question, never
finished into a real sentence. Fixed: _strip_dangling_example_parenthesis,
a structural (not phrase-list) safety net wired into _call_tinkerbell's
reply pipeline.

Part 2 - a turn ending with no question at all: after three consecutive
502s (Render redeploying - not this code's fault), the next successful
reply was "עוד לא כל הפרטים נסגרו - עדיין לא אפשר לאשר. נמשיך לסגור את
זה קודם." with no question mark anywhere - a dead end, the exact qa-s79
bug class _premature_approval_fallback_text already exists to avoid, except
this function never had a branch for still_open=="flights" (here,
destination_airports still unresolved) or still_open being None entirely -
both fell straight through to the fully generic, questionless sentence.
Fixed: the function now tries the real flight gap question first via
_flight_gap_question, exactly like every other caller.

Run: python3 tools/qa_round12_E_leak_and_no_final_question.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

from ariella_chat_clean import _strip_dangling_example_parenthesis, _premature_approval_fallback_text

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# --- Part 1: dangling example parenthesis ---

LIVE_LEAK_REPLY = (
    "מעולה, אז נהיה גמישים גם לקונקשן.\n\n"
    " (למשל יש שדות אזוריים שונים שיכולים לשרת את האזור) לתכנן גם מסלול ואטרקציות לחופשה הזו?"
)
cleaned = _strip_dangling_example_parenthesis(LIVE_LEAK_REPLY)
check(
    "finding E repro: the dangling '(למשל...)' aside is stripped",
    "למשל" not in cleaned,
)
check(
    "finding E repro: the real question survives intact",
    "לתכנן גם מסלול ואטרקציות לחופשה הזו?" in cleaned,
)
check(
    "finding E repro: the earlier complete sentence survives intact",
    "מעולה, אז נהיה גמישים גם לקונקשן." in cleaned,
)

# A legitimate "(למשל: ...)" sitting right AFTER the question it
# exemplifies (text before it, not after) must never be touched.
LEGITIMATE_EXAMPLE = "איזה סוג לינה מתאים לכם (למשל: מלון, דירה או צימר)?"
check(
    "regression: a legitimate example attached to its own question is untouched",
    _strip_dangling_example_parenthesis(LEGITIMATE_EXAMPLE) == LEGITIMATE_EXAMPLE,
)

# A reply with no "(למשל...)" at all passes through unchanged.
PLAIN_REPLY = "מעולה, נרשם. מה התקציב שלכם לאדם לטיסה?"
check(
    "regression: a reply without any '(למשל...)' passes through unchanged",
    _strip_dangling_example_parenthesis(PLAIN_REPLY) == PLAIN_REPLY,
)

# A parenthetical with no question after it at all is left alone (nothing
# to recover into - don't guess).
NO_QUESTION_AFTER = "זה מידע כללי. (למשל יש כמה אפשרויות לשקול כאן) זהו."
check(
    "regression: a dangling aside with no question after it is left alone",
    _strip_dangling_example_parenthesis(NO_QUESTION_AFTER) == NO_QUESTION_AFTER,
)


# --- Part 2: no-final-question dead end ---

STATE_FLIGHTS_STILL_OPEN = {
    "active_session": None,
    "next_session": None,
    "trip_type": "standard",
    "dates": {"departure": "2027-07-02", "return": "2027-07-06", "needs_confirmation": False},
    "travelers": {"adults": 3, "children": 0, "child_ages": []},
    "departure_airport": "TLV",
    "requested_services": ["flights"],
    "service_decisions": {"flights": {"wanted": True, "source": "destination_trip_intent"}},
    "destination": {"places": ["זדאר"], "mode": None, "status": "known"},
    "destination_airports": [],
    "flight": {"baggage": ["checked_bag"]},
    "budget_per_person": {"amount": 1100, "currency": "ILS", "status": "known"},
}
fallback = _premature_approval_fallback_text(STATE_FLIGHTS_STILL_OPEN)
check(
    "finding E repro: the fallback now asks a real question instead of a dead end",
    "?" in fallback,
)
check(
    "finding E repro: no longer the fully generic questionless sentence",
    fallback != "עוד לא כל הפרטים נסגרו - עדיין לא אפשר לאשר. נמשיך לסגור את זה קודם.",
)

# Regression: lodging/car/trip_planning still_open keeps working exactly as before.
STATE_LODGING_OPEN = {
    "active_session": "lodging", "next_session": None,
    "trip_type": "standard",
    "dates": {"departure": "2027-07-02", "return": "2027-07-06", "needs_confirmation": False},
    "travelers": {"adults": 2, "children": 0, "child_ages": []},
    "destination": {"places": ["זדאר"], "mode": None, "status": "known"},
    "destination_airports": ["ZAD"],
    "requested_services": ["flights", "lodging"],
    "service_decisions": {"lodging": {"wanted": True, "source": "x"}},
    "lodging": {"interested": "unknown", "details": {}},
}
lodging_fallback = _premature_approval_fallback_text(STATE_LODGING_OPEN)
check(
    "regression: a real lodging gap still produces its own question, not the generic fallback",
    "?" in lodging_fallback and "עוד לא כל הפרטים נסגרו" not in lodging_fallback,
)

# When genuinely nothing concrete is left (no flight gap, no domain gap),
# the generic sentence is still the honest last resort - never invented.
STATE_NOTHING_OPEN = {"active_session": None, "next_session": None, "destination_airports": ["TLV"], "flight": {}}
nothing_fallback = _premature_approval_fallback_text(STATE_NOTHING_OPEN)
check(
    "regression: with genuinely nothing concrete open, the generic honest fallback still returns",
    isinstance(nothing_fallback, str) and len(nothing_fallback) > 0,
)


print()
if FAILED:
    print(f"{len(FAILED)} CHECK(S) FAILED:")
    for name in FAILED:
        print(" -", name)
    sys.exit(1)
else:
    print("ALL ROUND12-E-LEAK-AND-NO-FINAL-QUESTION TESTS PASSED")
