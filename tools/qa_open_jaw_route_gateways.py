"""QA for the product owner's live clarification (relayed by Shaked,
Crete scenario 10): the flight summary must show THREE separate fields -
destination (the country/city the customer asked for), landing airport,
and return-departure airport - instead of lumping them into one "יעד"
field. Today it showed just "יעד: הרקליון" with no indication the route
actually lands in Chania and departs from Heraklion (an open-jaw route).

Root cause confirmed by reading the code (not guessed): scanner.py already
supports open-jaw search (is_open_jaw, reading return_departure_airports),
but _resolve_destination_airports_from_route (ariella_chat_clean.py) -
which derives the flight gateway from an approved day-by-day route - only
ever combined EVERY day's base into one destination_airports list. It
never recognized that the route's FIRST base is the arrival gateway and
its LAST base is the return-departure gateway when they genuinely differ.

Fixed: when the route's first and last day bases resolve to disjoint
airport codes, destination_airports gets only the first base's codes and
return_departure_airports gets only the last base's codes - exactly the
two fields scanner.py's open-jaw support already expects.

Run: python3 tools/qa_open_jaw_route_gateways.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

from ariella_chat_clean import _resolve_destination_airports_from_route

# --- 1. Genuine open-jaw: lands in Chania (west), ends in Heraklion (east) ---
state = {
    "trip_type": "standard",
    "trip_planning": {"details": {"route": [
        {"day": 1, "base": "חאניה"},
        {"day": 2, "base": "חאניה"},
        {"day": 3, "base": "חאניה"},
        {"day": 4, "base": "הרקליון"},
        {"day": 5, "base": "הרקליון"},
    ]}},
}
result = _resolve_destination_airports_from_route(state)
assert result["destination_airports"] == ["CHQ"], result.get("destination_airports")
assert result.get("return_departure_airports") == ["HER"], result.get("return_departure_airports")
print("PASS: open-jaw route (Chania in, Heraklion out) -> destination_airports=CHQ, return_departure_airports=HER")

# --- 2. Same base throughout (no open-jaw) -> single destination_airports,
# no return_departure_airports override ---
state2 = {
    "trip_type": "standard",
    "trip_planning": {"details": {"route": [
        {"day": 1, "base": "לרנקה"},
        {"day": 2, "base": "לרנקה"},
        {"day": 3, "base": "לרנקה"},
    ]}},
}
result2 = _resolve_destination_airports_from_route(state2)
assert result2["destination_airports"] == ["LCA"], result2.get("destination_airports")
assert "return_departure_airports" not in result2, result2.get("return_departure_airports")
print("PASS: single-base route (Larnaca throughout) -> destination_airports=LCA only, no open-jaw fields added")

# --- 3. First/last base TEXT differs ("קפריסין" the country vs "לרנקה"
# the city) but their resolved airports OVERLAP (Larnaca is one of
# Cyprus's own airports) -> correctly not treated as open-jaw ---
state3 = {
    "trip_type": "standard",
    "trip_planning": {"details": {"route": [
        {"day": 1, "base": "קפריסין"},
        {"day": 2, "base": "קפריסין"},
        {"day": 3, "base": "לרנקה"},
    ]}},
}
result3 = _resolve_destination_airports_from_route(state3)
assert "return_departure_airports" not in result3, result3.get("return_departure_airports")
print("PASS: first/last base text differs but overlaps in resolved airports -> treated as not open-jaw")

print("\nALL OPEN-JAW ROUTE GATEWAY TESTS PASSED")
