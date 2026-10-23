"""QA for dry-run 5d item 2 (Shaked, 23.10.2026, qa/reports/2026-10-23-
dryrun5d.md, scenario E) - BLOCKING, the THIRD live occurrence of the
exact same bug ("ברגם"->Bergamo with no question ever asked):

Turn 0 ("אני, אשתי והתינוק שלנו בן שנה לברגם, 12 עד 17 ביוני"): the
GENERAL extractor (EXTRACTOR_SYSTEM) resolved destination.places=
["ברגמו"] and destination_airports=["BGY"] directly, from its own world
knowledge, in the SAME turn the destination was first mentioned - never
going through _destination_gateway_answer_by_meaning at all (that
function's own gate, "destination_airports still empty", was already
false by the time anything could check it). _catalog_near_neighbor_
cities (Shlomo's approved structural signal, dry-run 5c item 1) was
wired into only that one function, so it never ran here.

Fix: _reresolve_ambiguous_fresh_destination runs right after the
existing _guard_destination_change_evidence (same call site, same
ordering), scoped to a genuinely FRESH first-time resolution this turn
(destination_airports empty before, non-empty now). It checks the
catalog-neighbor signal against destination_evidence - the model's own
verbatim quote, verified against the message - NEVER against the
already-corrected "ברגמו" (which would trivially exact-match itself and
suppress the signal via condition א). When exactly 2 real cities match,
the fresh resolution is reverted: destination_airports back to empty,
destination.places set to whichever form (quote as-is, or with one
leading Hebrew preposition stripped) produced the match - deliberately
leaving it as "a named but still-unresolved place" rather than building
a hint directly. _destination_gateway_answer_by_meaning (which already
runs later this SAME turn, unconditionally) then picks it up completely
normally through its own existing, already-tested mechanism.

Run: python3 tools/qa_dryrun5d_fresh_destination_ambiguity.py
"""
import inspect
import os
import sys
import json
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


KEY = os.getenv("ANTHROPIC_API_KEY", "test-key-not-real")
MODEL = "claude-sonnet-5"

TRIP_STATE_FRESH = {"requested_services": ["flights"], "service_decisions": {"flights": {"wanted": True}}}

# =====================================================================
# Part 1: _reresolve_ambiguous_fresh_destination - the core new guard.
# =====================================================================
TRIP_UPDATE_BERGAMO_RESOLVED = {
    "destination": {"places": ["ברגמו"], "mode": None, "status": "known"},
    "destination_airports": ["BGY"],
    "requested_services": ["flights"],
}
result = chat._reresolve_ambiguous_fresh_destination(
    TRIP_STATE_FRESH, dict(TRIP_UPDATE_BERGAMO_RESOLVED), "לברגם",
    "אני, אשתי והתינוק שלנו בן שנה לברגם, 12 עד 17 ביוני",
)
check("scenario E repro FIX: a fresh same-turn resolution to an ambiguous name is reverted - "
      "destination_airports goes back to empty",
      not result.get("destination_airports"))
check("scenario E repro FIX: destination.places is set to the raw (preposition-stripped) customer "
      "wording, never the already-corrected 'ברגמו' - left as a named-but-unresolved place",
      result.get("destination", {}).get("places") == ["ברגם"])

# Regression: an UNAMBIGUOUS fresh resolution (e.g. the business owner's
# own "פפוס" example) must sail through completely untouched.
TRIP_UPDATE_PAPHOS_RESOLVED = {
    "destination": {"places": ["פאפוס"], "mode": None, "status": "known"},
    "destination_airports": ["PFO"],
    "requested_services": ["flights"],
}
result_unambiguous = chat._reresolve_ambiguous_fresh_destination(
    TRIP_STATE_FRESH, dict(TRIP_UPDATE_PAPHOS_RESOLVED), "לפפוס", "אני ואמא שלי לפפוס, 20 עד 25 באפריל",
)
check("regression: an unambiguous fresh resolution (no catalog near-neighbor) is left completely untouched",
      result_unambiguous.get("destination_airports") == ["PFO"]
      and result_unambiguous.get("destination", {}).get("places") == ["פאפוס"])

# Regression: destination_airports already resolved BEFORE this turn (not
# a fresh resolution) - never this guard's job, that's _guard_destination_
# change_evidence's own (prior, unaffected) territory.
TRIP_STATE_ALREADY_RESOLVED = {"destination_airports": ["BGO"], "destination": {"places": ["ברגן"], "mode": None, "status": "known"}}
result_already_resolved = chat._reresolve_ambiguous_fresh_destination(
    TRIP_STATE_ALREADY_RESOLVED, dict(TRIP_UPDATE_BERGAMO_RESOLVED), "לברגם", "בעצם תחליפי לברגם",
)
check("regression: destination_airports already resolved before this turn (a CHANGE, not a fresh "
      "first-time resolution) is never this guard's job",
      result_already_resolved == dict(TRIP_UPDATE_BERGAMO_RESOLVED))

# Dry-run 5e (23.10.2026, Shaked's 4th live repro): destination_evidence
# was precisely the single point of failure this live case hit (the
# model's extraction omitted it, so the structural signal never ran at
# all despite the customer's own message containing the genuinely
# ambiguous "לברגם"). Shlomo's approved fix removed the dependency on
# destination_evidence entirely - the message's own tokens are scanned
# directly, so a genuinely ambiguous word IN THE MESSAGE still correctly
# reverts even with NO destination_evidence supplied at all.
result_no_evidence = chat._reresolve_ambiguous_fresh_destination(
    TRIP_STATE_FRESH, dict(TRIP_UPDATE_BERGAMO_RESOLVED), None,
    "אני, אשתי והתינוק שלנו בן שנה לברגם, 12 עד 17 ביוני",
)
check("dry-run 5e FIX: no destination_evidence at all, but the message itself contains the "
      "genuinely ambiguous 'לברגם' -> still correctly reverts (the whole point of the fix)",
      result_no_evidence.get("destination_airports") == [])
check("dry-run 5e FIX: the reverted destination.places carries the message's own ambiguous "
      "token (stripped form), for the gateway mechanism to pick up",
      result_no_evidence.get("destination", {}).get("places") == ["ברגם"])

# Regression: no destination_evidence AND the message itself has no
# catalog-ambiguous token either -> never reverts (nothing to find).
result_no_evidence_no_ambiguity = chat._reresolve_ambiguous_fresh_destination(
    TRIP_STATE_FRESH, dict(TRIP_UPDATE_BERGAMO_RESOLVED), None,
    "משהו לגמרי אחר שלא קשור ליעד בכלל",
)
check("regression: no destination_evidence and no ambiguous token anywhere in the message "
      "-> never reverts",
      result_no_evidence_no_ambiguity.get("destination_airports") == ["BGY"])

result_fake_evidence = chat._reresolve_ambiguous_fresh_destination(
    TRIP_STATE_FRESH, dict(TRIP_UPDATE_BERGAMO_RESOLVED), "לברגם", "משהו לגמרי אחר שלא קשור",
)
check("regression: destination_evidence that doesn't actually appear in the message is never trusted",
      result_fake_evidence.get("destination_airports") == ["BGY"])

# Regression: not a fresh resolution at all (destination_airports still
# empty even after the extractor - e.g. an uncatalogued place) - nothing
# to revert.
TRIP_UPDATE_STILL_UNRESOLVED = {"destination": {"places": ["רובין"], "mode": None, "status": "known"}, "destination_airports": []}
result_still_unresolved = chat._reresolve_ambiguous_fresh_destination(
    TRIP_STATE_FRESH, dict(TRIP_UPDATE_STILL_UNRESOLVED), None, "לרובין",
)
check("regression: destination_airports still empty after the extractor too - nothing to revert",
      result_still_unresolved == TRIP_UPDATE_STILL_UNRESOLVED)


# =====================================================================
# Part 2: end-to-end - after the revert, _destination_gateway_answer_by_
# meaning (which already runs later this SAME turn, unconditionally)
# picks the reverted place up completely normally and reframes its own
# one classifier call to name both real candidates - exactly like the
# "never pre-resolved at all" case already covered by qa_dryrun5c_catalog_
# ambiguity_signal.py, now reached via the OTHER path too.
# =====================================================================
_calls = []


def _fake_bergen_classifier(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other", **kw):
    if source == "classifier":
        _calls.append(system_static)
        return json.dumps({"evidence": "ברגם", "candidates": [
            {"city_en": "Bergen", "iata_code": "BGO"},
            {"city_en": "Bergamo", "iata_code": "BGY"},
        ]})
    return "{}"


trip_update_after_revert = chat._reresolve_ambiguous_fresh_destination(
    TRIP_STATE_FRESH, dict(TRIP_UPDATE_BERGAMO_RESOLVED), "לברגם",
    "אני, אשתי והתינוק שלנו בן שנה לברגם, 12 עד 17 ביוני",
)
with patch.object(chat, "_post_claude", side_effect=_fake_bergen_classifier):
    gateway_result = chat._destination_gateway_answer_by_meaning(
        "אני, אשתי והתינוק שלנו בן שנה לברגם, 12 עד 17 ביוני", [], trip_update_after_revert,
    )
check("end-to-end FIX: after the revert, the existing gateway mechanism picks up the reverted "
      "place and reframes its one classifier call to name BOTH real candidates",
      "Bergen" in _calls[0] and "Bergamo" in _calls[0] and len(_calls) == 1)
check("end-to-end FIX: nothing is written to destination_airports - a one-turn ambiguous hint is "
      "produced instead, exactly the scenario E fix",
      not gateway_result.get("destination_airports") and bool(gateway_result.get("_destination_ambiguous_hint")))


# =====================================================================
# Part 3: wiring check - the new guard is actually called from the real
# per-turn handler, in the right place (right after _guard_destination_
# change_evidence, before the _destination_ambiguous_hint pop further
# down so the reverted destination survives to the later gateway call).
# =====================================================================
_chat_impl_source = inspect.getsource(chat._chat_clean_impl)
check("wiring check: _reresolve_ambiguous_fresh_destination is actually called from the real "
      "per-turn handler (not just defined, never used)",
      "_reresolve_ambiguous_fresh_destination(trip_state, trip_update, destination_evidence, message)" in _chat_impl_source)
_guard_pos = _chat_impl_source.index("_guard_destination_change_evidence(trip_state, trip_update, destination_evidence, message)")
_reresolve_pos = _chat_impl_source.index("_reresolve_ambiguous_fresh_destination(trip_state, trip_update, destination_evidence, message)")
_gateway_pos = _chat_impl_source.index('_destination_gateway_answer_by_meaning(message, history, trip_update)')
check("wiring check: ordering is correct - change-evidence guard, then the new fresh-ambiguity "
      "check, then (later) the existing gateway-answer call that actually asks the question",
      _guard_pos < _reresolve_pos < _gateway_pos)


if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DRYRUN5D-FRESH-DESTINATION-AMBIGUITY TESTS PASSED")
