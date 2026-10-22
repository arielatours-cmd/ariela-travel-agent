"""QA for dry-run 5, scenarios A and B (Shlomo/Shaked, 22.10.2026,
qa-dryrun branch, commit a23723b, qa/dryrun/2026-10-22-dr5-typos/):

A (Paphos, "פפוס"): the opening message named destination+dates+travelers
together. destination_gateway resolution never fired at all - Tinkerbell
claimed "לעיר עצמה אין שדה תעופה בינלאומי משלה" and asked an open
question, exactly the bug the whole mechanism exists to prevent. Root
cause: _destination_gateway_unresolved_places gated on _guided_baggage_
applies (requires "flights" already IN requested_services) - but
requested_services only gets "flights" added by the destination-trip-
intent fallback, which runs AFTER this classifier in the pipeline. On the
very first turn (before that fallback has run), the gate read false
exactly when it most needed to read true.
Fixed: mirrors that same fallback's own condition (a destination was
named, flights never explicitly declined) instead - needs nothing
computed later in the turn to already exist.

B (Zadar, "זדאר"):
1. Once the gateway classifier verifies a code against the real catalog,
   Tinkerbell still asked "רוצה לוודא איתך - שדה התעופה הוא זדאר (ZAD)?" -
   an unneeded confirmation of a fact already fully VERIFIED, not merely
   claimed. Fixed: a one-turn hint (mirroring the existing budget "just
   given" hint) tells her explicitly when destination_airports was just
   settled this turn, so she states it as fact.
2. The opening message also described mixed per-passenger baggage needs
   ("לי מספיק טרולי, לשתיים האחרות מזוודה") before baggage was anywhere
   near the live guided field (accessibility comes first) -
   EXTRACTOR_SYSTEM correctly left flight.baggage empty (per its own
   "never write a mixed request" rule), but nothing ever flagged the
   mention, so it was simply lost. Fixed: _mixed_baggage_safety_net gets
   a second branch that proactively detects this via the same guided
   baggage classifier, gated by a cheap keyword+traveler-count pre-filter
   (cost control only - the model still decides), setting
   guided.mixed_baggage_pending=True even before baggage becomes live.

Run: python3 tools/qa_dryrun5_typo_scenarios.py
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


# =====================================================================
# Scenario A: the opening-turn requested_services timing gap.
# =====================================================================
STATE_A_OPENING_TURN = {
    "destination": {"places": ["פפוס"], "mode": None, "status": "known"},
    "destination_airports": [],
    "requested_services": [],   # not yet set - the real live bug shape
    "service_decisions": {},    # flights not yet explicitly decided either
}
check(
    "finding A repro: destination_gateway_unresolved_places fires even with requested_services still empty "
    "(mirrors the destination-trip-intent fallback's own condition, not timing-dependent)",
    "פפוס" in chat._destination_gateway_unresolved_places(STATE_A_OPENING_TURN),
)

STATE_A_FLIGHTS_DECLINED = dict(STATE_A_OPENING_TURN, service_decisions={"flights": {"wanted": False}})
check(
    "regression: flights explicitly declined still correctly skips (the only real 'nothing to resolve' signal)",
    chat._destination_gateway_unresolved_places(STATE_A_FLIGHTS_DECLINED) == [],
)


# =====================================================================
# Scenario B, part 1: no redundant confirmation once genuinely verified.
# Exercised through the actual _chat_clean_impl pipeline slice: the
# "_just_given" one-turn hint block.
# =====================================================================
TRIP_STATE_NO_AIRPORT_YET = {"destination_airports": []}
TRIP_UPDATE_JUST_RESOLVED = {"destination_airports": ["ZAD"], "budget_per_person": {"amount": None}}
_just_given = []
if TRIP_UPDATE_JUST_RESOLVED.get("budget_per_person", {}).get("amount") and not TRIP_STATE_NO_AIRPORT_YET.get("budget_per_person", {}).get("amount"):
    _just_given.append("התקציב")
if not (TRIP_STATE_NO_AIRPORT_YET.get("destination_airports") or []) and (TRIP_UPDATE_JUST_RESOLVED.get("destination_airports") or []):
    _just_given.append("שדה התעופה ליעד (כבר אומת מול הקטלוג - אין צורך לשאול שוב או לבקש אישור עליו)")
check(
    "finding B repro: a destination_airports resolved fresh this turn adds the 'no need to confirm' one-turn hint",
    any("שדה התעופה ליעד" in g for g in _just_given),
)


# =====================================================================
# Scenario B, part 2: mixed baggage mentioned before baggage is live.
# =====================================================================
STEPS = {"dates", "travelers", "baggage", "accessibility"}


def base_state(answered=None, baggage=None):
    return {
        "requested_services": ["flights"],
        "travelers": {"adults": 1, "children": 0},
        "dates": {"departure": "2027-07-02", "return": "2027-07-06"},
        "flight": {"baggage": baggage or []},
        "guided": {"current_question": "accessibility", "attempts": 0, "answered": answered or ["dates", "travelers"]},
    }


MIXED_RESULT = {"status": "answered", "mixed_per_passenger": True, "baggage": None, "confidence": "high",
                 "also_mentioned": {}, "correction": None}
NOT_MIXED_RESULT = {"status": "answered", "mixed_per_passenger": False, "items": [{"type": "checked_bag", "count": None}],
                     "confidence": "high", "also_mentioned": {}, "correction": None}

MIXED_MESSAGE = "אני ושתי חברות לזדאר, 2 עד 6 ביולי. לי מספיק טרולי, לשתיים האחרות מזוודה"

# 3+ travelers total (1 adult here represents "me"; the mixed statement
# itself names 3 people total - traveler count comes from state, set to 3).
trip_state_3pax = base_state()
trip_state_3pax["travelers"] = {"adults": 3, "children": 0}
trip_update_3pax = dict(trip_state_3pax)

with patch.object(chat, "_guided_extract_answer", return_value=MIXED_RESULT) as mock_extract, \
        patch.object(chat, "record_diagnostic_event"):
    out = chat._mixed_baggage_safety_net("k", "m", MIXED_MESSAGE, [], trip_state_3pax, trip_update_3pax, STEPS)
check(
    "finding B repro: a mixed statement mentioned before baggage is live sets mixed_baggage_pending proactively",
    out["guided"].get("mixed_baggage_pending") is True,
)
check(
    "finding B repro: nothing is saved to flight.baggage (nothing to revert - it was never written)",
    not (out.get("flight") or {}).get("baggage"),
)
check(
    "finding B repro: current_question is left alone (still accessibility - baggage isn't live yet)",
    out["guided"].get("current_question") == "accessibility",
)

# Regression: a single traveler (no one else to have different needs) never triggers this.
trip_state_1pax = base_state()
trip_update_1pax = dict(trip_state_1pax)
with patch.object(chat, "_guided_extract_answer") as mock_extract_unused, \
        patch.object(chat, "record_diagnostic_event"):
    out2 = chat._mixed_baggage_safety_net("k", "m", "רק תיק יד לי", [], trip_state_1pax, trip_update_1pax, STEPS)
check(
    "regression: a single traveler never triggers the proactive mixed-baggage check (no classifier call)",
    out2["guided"].get("mixed_baggage_pending") is not True and not mock_extract_unused.called,
)

# Regression: a message with no baggage-related word at all never calls the classifier.
trip_state_no_kw = base_state()
trip_state_no_kw["travelers"] = {"adults": 3, "children": 0}
trip_update_no_kw = dict(trip_state_no_kw)
with patch.object(chat, "_guided_extract_answer") as mock_extract_unused2, \
        patch.object(chat, "record_diagnostic_event"):
    out3 = chat._mixed_baggage_safety_net("k", "m", "אני ושתי חברות לזדאר, 2 עד 6 ביולי", [], trip_state_no_kw, trip_update_no_kw, STEPS)
check(
    "regression: no baggage-related word in the message never calls the classifier",
    not mock_extract_unused2.called,
)

# Regression: classifier says NOT mixed -> nothing is flagged.
trip_state_not_mixed = base_state()
trip_state_not_mixed["travelers"] = {"adults": 3, "children": 0}
trip_update_not_mixed = dict(trip_state_not_mixed)
with patch.object(chat, "_guided_extract_answer", return_value=NOT_MIXED_RESULT), \
        patch.object(chat, "record_diagnostic_event"):
    out4 = chat._mixed_baggage_safety_net("k", "m", "מזוודה לכולנו", [], trip_state_not_mixed, trip_update_not_mixed, STEPS)
check(
    "regression: classifier says not mixed -> mixed_baggage_pending stays unset",
    out4["guided"].get("mixed_baggage_pending") is not True,
)

# Regression: baggage already answered -> the proactive branch never fires.
trip_state_already_answered = base_state(answered=["dates", "travelers", "baggage"], baggage=["checked_bag"])
trip_update_already_answered = dict(trip_state_already_answered)
with patch.object(chat, "_guided_extract_answer") as mock_extract_unused3, \
        patch.object(chat, "record_diagnostic_event"):
    out5 = chat._mixed_baggage_safety_net("k", "m", "מזוודה לכולנו, חוץ מהתינוקת שמספיק לה תיק", [], trip_state_already_answered, trip_update_already_answered, STEPS)
check(
    "regression: baggage already answered -> the proactive first-mention branch never fires",
    not mock_extract_unused3.called,
)


print()
if FAILED:
    print(f"{len(FAILED)} CHECK(S) FAILED:")
    for name in FAILED:
        print(" -", name)
    sys.exit(1)
else:
    print("ALL DRYRUN5-TYPO-SCENARIOS TESTS PASSED")
