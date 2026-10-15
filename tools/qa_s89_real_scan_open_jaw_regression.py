"""QA for Shaked's live report (2026-10-13/14, qa-s89, Cyprus, the first
real paid scan, trip 209, commit 6ceea8e): the single 🔴 finding from that
scan.

Root cause confirmed by reading the code (not guessed): the route the
customer actually approved started AND ended in Larnaca (a normal round
trip - fly in, tour the island, fly home from the same city), but
trip_planning.details.route only ever got backfilled from
_extract_route_bases_from_approved_text (qa-s84's fix) - which can only
see OVERNIGHT ("לינה ב-X") mentions. A same-day return leg to the origin
with no further overnight stay there is invisible to that extraction, so
its last mentioned base was Paphos (the last place the customer actually
slept), not Larnaca (the true last-day location). _resolve_destination_
airports_from_route then confidently treated this as a genuine open-jaw
route and set return_departure_airports=PFO - and because this function
re-derives on every turn with no "already resolved, respect it" guard, it
kept re-asserting PFO even after the customer explicitly corrected it in
chat and Ariella's own reply confirmed the correction. The real flight
search then ran with the wrong return airport.

Two independent fixes:
1. Route data backfilled from the lodging-text extraction is now flagged
   (route_inferred_from_lodging_text) and the open-jaw gateway SPLIT never
   trusts it - only a route the model filled in itself as real structured
   JSON (which could include a same-day return day with no lodging
   implication) is reliable enough for that split.
2. Once return_departure_airports already holds a value (from any source,
   including a customer's own correction), this derivation never
   re-clobbers it on a later turn.

Run: python3 tools/qa_s89_real_scan_open_jaw_regression.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import ariella_chat_clean as chat

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# --- 1. The exact qa-s89 shape: a route inferred from lodging-text that
#        only ever mentions Larnaca then Paphos (the customer's real route
#        starts AND ends in Larnaca, with a same-day return leg the text
#        extraction can't see) must never be treated as a genuine open-jaw ---
inferred_state = {
    "trip_type": "standard",
    "trip_planning": {"details": {
        "route": [{"base": "לרנקה"}, {"base": "פאפוס"}],
        "route_inferred_from_lodging_text": True,
    }},
}
result = chat._resolve_destination_airports_from_route(inferred_state)
check("a lodging-text-inferred route never triggers the open-jaw gateway split",
      "return_departure_airports" not in result)
check("destination_airports still gets a sane (non-empty) value from the union of both cities",
      bool(result.get("destination_airports")))

# --- 2. Regression guard: a route the model filled in as REAL structured
#        JSON (no inferred flag) still gets the genuine open-jaw split -
#        this must not silently stop working ---
real_json_state = {
    "trip_type": "standard",
    "trip_planning": {"details": {"route": [
        {"day": 1, "base": "חאניה"}, {"day": 2, "base": "חאניה"},
        {"day": 3, "base": "הרקליון"}, {"day": 4, "base": "הרקליון"},
    ]}},
}
real_result = chat._resolve_destination_airports_from_route(real_json_state)
check("a genuine model-JSON open-jaw route (no inferred flag) still splits correctly",
      real_result.get("destination_airports") == ["CHQ"] and real_result.get("return_departure_airports") == ["HER"])

# --- 3. The exact qa-s89 re-clobbering shape: once return_departure_
#        airports is already set (e.g. by the customer's own correction),
#        this function never overwrites it again on a later turn, even
#        with the same disjoint-looking route still in state ---
already_corrected_state = {
    "trip_type": "standard",
    "destination_airports": ["LCA"],
    "return_departure_airports": ["LCA"],
    "trip_planning": {"details": {"route": [
        {"day": 1, "base": "לרנקה"}, {"day": 2, "base": "לרנקה"},
        {"day": 3, "base": "פאפוס"}, {"day": 4, "base": "פאפוס"},
    ]}},
}
corrected_result = chat._resolve_destination_airports_from_route(already_corrected_state)
check("an already-set return_departure_airports (e.g. a customer correction) is never re-clobbered",
      corrected_result.get("return_departure_airports") == ["LCA"])

# --- 4. Regression guard: the original qa_open_jaw_route_gateways.py
#        scenarios (no pre-set return_departure_airports) still behave
#        identically - this isn't re-tested in full here since that file
#        already covers it end to end; just confirm the single-base (no
#        open-jaw at all) case still adds no return field ---
single_base_state = {
    "trip_type": "standard",
    "trip_planning": {"details": {"route": [
        {"day": 1, "base": "לרנקה"}, {"day": 2, "base": "לרנקה"},
    ]}},
}
single_result = chat._resolve_destination_airports_from_route(single_base_state)
check("a single-base route (no open-jaw) still adds no return_departure_airports field",
      "return_departure_airports" not in single_result)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL QA-S89 REAL-SCAN REGRESSION TESTS PASSED")
