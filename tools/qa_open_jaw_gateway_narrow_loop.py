"""QA for Shaked's live report (2026-10-13, Cyprus real-scan test, qa-s75):
flight.gateway_narrow kept firing every turn after the route itself had
already settled an open-jaw (land in Paphos, return from Larnaca), re-
asking the exact same "יש כמה שדות אפשריים... לצמצם לשדה אחד או שניהם?"
question even after the customer had explicitly confirmed the arrangement
("מתאים ככה"). The question only makes sense for a genuinely undecided
SINGLE gateway choice - once return_departure_airports holds its own,
different, already-resolved value, there's nothing left to narrow.

_required_state_gaps now excludes flight.gateway_narrow once
return_departure_airports is set and differs from destination_airports
(an open-jaw already resolved), while still asking it for a genuine
undecided multi-candidate single-direction case.

Run: python3 tools/qa_open_jaw_gateway_narrow_loop.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import ariella_chat_clean as chat

base_state = {
    "trip_type": "standard",
    "requested_services": ["flights", "trip_planning"],
    "service_decisions": {
        "flights": {"wanted": True}, "trip_planning": {"wanted": True},
        "lodging": {"wanted": False}, "car": {"wanted": False},
    },
    "session_status": {"flights": "active", "trip_planning": "complete", "lodging": "declined", "car": "declined"},
    "destination": {"places": ["קפריסין"], "mode": "specific"},
    "trip_planning": {
        "interested": True, "approved": True,
        "details": {"style": "x", "pace": "x", "route": [{"base": "פאפוס"}, {"base": "לרנקה"}]},
    },
    "dates": {"departure": "2026-12-06", "return": "2026-12-11", "needs_confirmation": False},
    "travelers": {"adults": 2},
    "departure_airport": "TLV",
    "budget_per_person": {"amount": 3000, "currency": "ILS", "status": "known"},
    "flight": {"baggage": ["checked_bag"]},
}

state_a = dict(base_state)
state_a["destination_airports"] = ["PFO"]
state_a["return_departure_airports"] = ["LCA"]
gaps_a = chat._required_state_gaps(state_a)
assert "flight.gateway_narrow" not in gaps_a, gaps_a
print("PASS: open-jaw already resolved (Paphos in, Larnaca out) -> gateway_narrow never re-asked")

state_b = dict(base_state)
state_b["destination_airports"] = ["PFO", "LCA"]
gaps_b = chat._required_state_gaps(state_b)
assert "flight.gateway_narrow" in gaps_b, gaps_b
print("PASS: genuine undecided multi-candidate, no open-jaw -> gateway_narrow still asked")

# A same-airport round trip (no open-jaw at all, return_departure_airports
# simply mirrors destination_airports) must not be mistaken for a resolved
# open-jaw and must still ask if there's real ambiguity.
state_c = dict(base_state)
state_c["destination_airports"] = ["PFO", "LCA"]
state_c["return_departure_airports"] = ["PFO", "LCA"]
gaps_c = chat._required_state_gaps(state_c)
assert "flight.gateway_narrow" in gaps_c, gaps_c
print("PASS: return_departure_airports mirroring destination_airports (no real open-jaw) -> still asked")

print("\nALL OPEN-JAW GATEWAY-NARROW LOOP TESTS PASSED")
