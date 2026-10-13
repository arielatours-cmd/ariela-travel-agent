"""QA for Shaked's live report (2026-10-12, f2ecfed round, scenario 11 -
Florence): a customer who already booked their own flights ("כבר הזמנו
טיסות... צריכה רק תכנון מסלול בטוסקנה ולינה") got asked "לאן תרצי לטוס?"
turns later, answering the LODGING question after route approval.

Root cause: _required_state_gaps (ariella_chat_clean.py) built its working
"services" set from the raw requested_services list (the extractor's own
per-turn, full-history re-read) and only ever ADDED a service to it when
service_decisions said wanted=True - it never REMOVED one for wanted=False.
_keep_declines correctly keeps service_decisions.flights wanted=False
across turns, but if the extractor's own requested_services re-includes
"flights" on a later turn (independently of that), the stale/re-added
entry still made it into the "flights" session's gaps (departure_airport,
destination_airports, dates...), producing the gap question even though
flights was genuinely declined. Fixed by having an explicit wanted=False
decision discard the service from that turn's working set, not just skip
adding it.

Run: python3 tools/qa_declined_flights_gap_leak.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

from ariella_chat_clean import _required_state_gaps, _session_gaps

base_state = {
    "trip_type": "standard",
    "destination": {"places": ["פירנצה"], "mode": "specific"},
    "dates": {"departure": "2027-05-10", "return": "2027-05-17", "needs_confirmation": False},
    "travelers": {"adults": 2, "children": 0, "child_ages": []},
    "trip_planning": {"details": {"approved": True}},
    "lodging": {"details": {}},
    "car": {},
    "flight": {},
}

# --- 1. requested_services STILL raw-includes "flights" (the extractor's own
# stale re-add) even though service_decisions correctly says wanted=False ---
state = dict(base_state)
state["requested_services"] = ["flights", "trip_planning", "lodging"]
state["service_decisions"] = {
    "flights": {"wanted": False, "source": "already_booked_elsewhere"},
    "trip_planning": {"wanted": True, "source": "explicit_named_accept"},
    "lodging": {"wanted": True, "source": "explicit_named_accept"},
}

gaps = _required_state_gaps(state)
flight_gaps = [g for g in gaps if g == "departure_airport" or g.startswith("destination_airports") or g.startswith("flight.")]
assert not flight_gaps, f"flights gaps leaked despite explicit decline: {flight_gaps}"
print("PASS: flights explicitly declined -> no flight-session gaps, even though requested_services still raw-lists 'flights'")

flight_session_gaps = _session_gaps(state, "flights")
assert flight_session_gaps == [], f"_session_gaps('flights') should be empty once declined, got {flight_session_gaps}"
print("PASS: _session_gaps('flights') is empty -> _flight_gap_question has nothing to ask")

# --- 2. lodging gaps still correctly reported (the decline must not swallow
# OTHER services' real gaps) ---
lodging_gaps = [g for g in gaps if g.startswith("lodging.")]
assert lodging_gaps, f"lodging gaps should still be reported, got none: {gaps}"
print(f"PASS: lodging gaps still reported normally ({lodging_gaps})")

# --- 3. Sanity: when flights is genuinely wanted, its gaps DO appear ---
state2 = dict(base_state)
state2["requested_services"] = ["flights"]
state2["service_decisions"] = {"flights": {"wanted": True, "source": "destination_implies_flights"}}
state2["dates"] = {"departure": None, "return": None, "needs_confirmation": True}
gaps2 = _required_state_gaps(state2)
assert "dates" in gaps2, gaps2
print("PASS: flights genuinely wanted -> its real gaps (e.g. dates) still appear")

print("\nALL DECLINED-FLIGHTS GAP-LEAK TESTS PASSED")
