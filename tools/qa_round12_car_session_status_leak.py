"""QA for round-12 live finding C (Shlomo/Shaked, 22.10.2026, qa-dryrun
branch "shaked", qa/live/2026-10-22-run12/r12_C.log + chat_resp_r12c.jsonl,
commit 39feca9):

Real transcript (Paphos, 2 travelers): after trip_planning was declined,
Tinkerbell asked a single yes/no about lodging only
(post_flight_offer=["lodging"]). The customer answered "יש לנו" (we already
have it). The code correctly read this as declining lodging - but in the
same turn, car (never mentioned, never offered, never decided) flipped
straight from "pending" to "complete" with no decision ever recorded for it
(service_decisions has no "car" key at all).

Root cause, confirmed by reading _parse_trip_update/_merge_trip_state/
_advance_sessions directly: EXTRACTOR_SYSTEM's own JSON schema (the
trip_update example) includes session_status/active_session as fields the
model fills in on every turn, and _parse_trip_update returned them
unfiltered straight into what _merge_trip_state(trip_state, extracted)
merges wholesale into trip_update. Whenever the turn's own code-driven
logic (post_flight_offer answer handling, explicit decline detectors, etc.)
doesn't happen to touch a particular domain, whatever session_status value
the model itself guessed for it survives untouched - even "complete" for a
domain nobody has ever engaged with. lodging got the right value only
because the post_flight_offer code path explicitly overwrites it after the
merge; car, never in that turn's post_flight_offer list, had nothing to
correct the model's own guess.

Fixed: _parse_trip_update now strips session_status/active_session from
the parsed trip_update before anything else ever sees it - exactly the
same "code-only, never the model's" rule already established for
search_confirmed. EXTRACTOR_SYSTEM's prompt text updated to match (no
longer asks the model to compute these, just to leave them as given).

Run: python3 tools/qa_round12_car_session_status_leak.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

from ariella_chat_clean import _parse_trip_update, _merge_trip_state, _advance_sessions

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# --- 1. _parse_trip_update strips the model's own session_status/active_session ---

_RAW_WITH_HALLUCINATED_STATUS = json.dumps({
    "restart_request": False, "restart_evidence": None, "dates_evidence": None,
    "destination_evidence": None, "trip_type_evidence": None, "relative_date_hint": None,
    "relative_date_hint_evidence": None, "link_request": False, "link_request_evidence": None,
    "trip_update": {
        "destination": {"places": ["פפוס"], "mode": None, "status": "known"},
        "service_decisions": {"lodging": {"wanted": False, "source": "extractor"}},
        # The exact live shape: the model wrote a full session_status guess,
        # marking car "complete" even though nothing ever decided it.
        "session_status": {"flights": "complete", "lodging": "declined", "car": "complete", "trip_planning": "declined"},
        "active_session": None,
    },
}, ensure_ascii=False)

parsed = _parse_trip_update(_RAW_WITH_HALLUCINATED_STATUS)
check("_parse_trip_update strips session_status from the model's raw JSON", "session_status" not in parsed)
check("_parse_trip_update strips active_session from the model's raw JSON", "active_session" not in parsed)
check("_parse_trip_update keeps unrelated fields (destination) intact", parsed.get("destination", {}).get("places") == ["פפוס"])
check("_parse_trip_update keeps service_decisions intact", parsed.get("service_decisions", {}).get("lodging", {}).get("wanted") is False)


# --- 2. Even a raw JSON with no code-only fields at all parses normally ---

_RAW_NORMAL = json.dumps({
    "restart_request": False, "restart_evidence": None, "dates_evidence": None,
    "destination_evidence": None, "trip_type_evidence": None, "relative_date_hint": None,
    "relative_date_hint_evidence": None, "link_request": False, "link_request_evidence": None,
    "trip_update": {"budget_per_person": {"amount": 1300, "currency": "ILS", "status": "known"}},
}, ensure_ascii=False)
parsed_normal = _parse_trip_update(_RAW_NORMAL)
check("regression: ordinary parsing without session_status/active_session still works", parsed_normal.get("budget_per_person", {}).get("amount") == 1300)


# --- 3. End-to-end: the real round-12 turn-9 state (car genuinely 'pending',
#        never requested/decided) merged with a hallucinated car='complete'
#        extraction must NOT let car become 'complete' ---

TRIP_STATE_BEFORE_TURN_9 = {
    "destination": {"places": ["פפוס"], "mode": None, "status": "known"},
    "destination_airports": [],
    "travelers": {"adults": 2, "children": 0, "child_ages": []},
    "dates": {"departure": "2027-04-20", "return": "2027-04-25", "needs_confirmation": False},
    "budget_per_person": {"amount": 1300, "currency": "ILS", "status": "known"},
    "car": {"interested": "unknown", "details": {}},
    "lodging": {"interested": "unknown", "details": {}},
    "trip_planning": {"interested": "unknown", "details": {}},
    "requested_services": ["flights"],
    "service_decisions": {
        "flights": {"source": "destination_trip_intent", "wanted": True},
        "trip_planning": {"source": "post_flight_offer", "wanted": False},
    },
    "session_status": {"car": "pending", "flights": "complete", "lodging": "pending", "trip_planning": "declined"},
    "active_session": None,
    "post_flight_offer": ["lodging"],
}

# What the live extractor's raw JSON genuinely contained this turn (per the
# mechanism above) before our fix: a fresh, wrong session_status guess.
_RAW_TURN_9 = json.dumps({
    "restart_request": False, "restart_evidence": None, "dates_evidence": None,
    "destination_evidence": None, "trip_type_evidence": None, "relative_date_hint": None,
    "relative_date_hint_evidence": None, "link_request": False, "link_request_evidence": None,
    "trip_update": {
        "session_status": {"flights": "complete", "lodging": "declined", "car": "complete", "trip_planning": "declined"},
        "active_session": None,
    },
}, ensure_ascii=False)

extracted_turn_9 = _parse_trip_update(_RAW_TURN_9)
merged = _merge_trip_state(TRIP_STATE_BEFORE_TURN_9, extracted_turn_9)
check(
    "finding C repro: car stays 'pending' after merge - never silently 'complete' from the model's own guess",
    merged.get("session_status", {}).get("car") == "pending",
)
check(
    "finding C repro: flights/lodging/trip_planning carry over from trip_state untouched",
    merged.get("session_status", {}).get("flights") == "complete"
    and merged.get("session_status", {}).get("lodging") == "pending"
    and merged.get("session_status", {}).get("trip_planning") == "declined",
)

# Now apply the SAME post_flight_offer decline the real code applies for
# "יש לנו" (lodging=False, the one domain genuinely offered/decided this
# turn) and confirm _advance_sessions correctly queues car as the next
# pending domain to ask about - never completing it out from under the
# customer.
merged["service_decisions"] = dict(merged.get("service_decisions") or {}, lodging={"wanted": False, "source": "post_flight_offer"})
statuses = dict(merged.get("session_status") or {})
statuses["lodging"] = "declined"
merged["session_status"] = statuses
merged["post_flight_offer"] = []

advanced = _advance_sessions(merged)
check(
    "finding C repro: after the real lodging decline is applied, car is STILL 'pending' (not completed)",
    advanced.get("session_status", {}).get("car") == "pending",
)
check(
    "finding C repro: _advance_sessions correctly queues car as the next domain to ask about",
    advanced.get("next_session") == "car",
)
check(
    "finding C repro: ready_for_summary is still False - car was never actually decided",
    advanced.get("ready_for_summary") is False,
)


print()
if FAILED:
    print(f"{len(FAILED)} CHECK(S) FAILED:")
    for name in FAILED:
        print(" -", name)
    sys.exit(1)
else:
    print("ALL ROUND12-CAR-SESSION-STATUS-LEAK TESTS PASSED")
