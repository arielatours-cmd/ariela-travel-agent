"""QA for round-12 live finding E, no-final-question part (Shlomo/Shaked,
22.10.2026, qa-dryrun branch "shaked", qa/live/2026-10-22-run12/r12_E.log,
Zadar):

A turn ending with no question at all: after three consecutive 502s
(Render redeploying - not this code's fault), the next successful reply
was "עוד לא כל הפרטים נסגרו - עדיין לא אפשר לאשר. נמשיך לסגור את זה
קודם." with no question mark anywhere - a dead end, the exact qa-s79 bug
class _premature_approval_fallback_text already exists to avoid, except
this function never had a branch for still_open=="flights" (here,
destination_airports still unresolved) or still_open being None entirely -
both fell straight through to the fully generic, questionless sentence.
Fixed: the function now tries the real flight gap question first via
_flight_gap_question, exactly like every other caller.

(The other two parts of this finding - the internal-reasoning-leak
parenthetical and the self-picked baggage type - are covered by
tools/qa_round12_baggage_self_pick_guard.py and TINKERBELL_SYSTEM's own
prompt instruction against unfinished example asides, per Shaked's review
that a regex-deletion mechanism was the wrong fix for the leak - see that
test file and ariella_chat_clean.py's TINKERBELL_SYSTEM rule 119.)

Run: python3 tools/qa_round12_E_leak_and_no_final_question.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

from ariella_chat_clean import _premature_approval_fallback_text

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


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
    print("ALL ROUND12-E-NO-FINAL-QUESTION TESTS PASSED")
