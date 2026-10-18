"""QA for the business owner's explicit instruction (2026-10-14, after
Shaked's real-scan testing found every lodging result clustered in a
single city although the approved route spent several nights elsewhere):
lodging needs a separate location + date range PER STOP on the route
("lodging location 1, lodging location 2, location 3...", each with its
own dates, remembered from the route), and the real search has to look
for that place on those dates - not one combined city/date range for the
whole trip.

Part 1 (ariella_chat_clean.py): _extract_route_night_segments_from_
approved_text pulls (location, nights) pairs from the route's own intro
summary ("לרנקה (לילה אחד), פאפוס (שני לילות)..."), handling both Hebrew
night-count word orders (the "לילה אחד" vs "שני לילות" grammar quirk).
_route_night_segments_to_date_ranges turns that into concrete per-location
check-in/check-out dates by walking forward from the trip's departure
date. _resolve_lodging_locations_from_route wires both into lodging.
details.location_segments, best-effort only - falling back to nothing
(never guessing) when the route's text doesn't have this specific shape.

Part 2 (public_site.py): _run_lodging_search runs one SerpApi search per
segment when location_segments is present, tagging each result with which
stop it's for; falls back to the single-city search otherwise, now
preferring lodging_location's first named area over blindly defaulting to
the alphabetically-first destination airport code (the root cause Shaked's
real scan exposed).

Run: python3 tools/qa_lodging_per_location_segments.py
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import ariella_chat_clean as chat

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# --- 1. Night-count extraction handles both Hebrew word orders: "לילה
#        אחד" (noun-then-number, exactly one) and "שני לילות"/"3 לילות"
#        (number-then-noun, two or more) ---
intro_text = "הנה המסלול: לרנקה (לילה אחד), פאפוס (שני לילות), לימסול (3 לילות)."
segs = chat._extract_route_night_segments_from_approved_text(intro_text)
check("extracts all three stops with correct night counts (word and digit forms)",
      segs == [("לרנקה", 1), ("פאפוס", 2), ("לימסול", 3)])

# --- 2. No intro-summary phrasing at all -> empty, never guesses ---
check("text without the parenthetical intro summary yields nothing (never guesses)",
      chat._extract_route_night_segments_from_approved_text("מסלול יפה, תיהנו מהטיול!") == [])

# --- 3. Date-range walk: segments turn into consecutive check-in/check-out
#        dates starting from the trip's departure date, summing to the
#        full trip length ---
ranges = chat._route_night_segments_to_date_ranges(segs, "2026-12-06")
check("date ranges walk forward consecutively from departure, each check-out is the next check-in",
      ranges == [
          {"location": "לרנקה", "date_from": "2026-12-06", "date_to": "2026-12-07", "nights": 1},
          {"location": "פאפוס", "date_from": "2026-12-07", "date_to": "2026-12-09", "nights": 2},
          {"location": "לימסול", "date_from": "2026-12-09", "date_to": "2026-12-12", "nights": 3},
      ])

# --- 4. No departure date -> empty, never crashes ---
check("missing departure date -> empty list, never crashes",
      chat._route_night_segments_to_date_ranges(segs, None) == [])

# --- 5. Full integration: _resolve_lodging_locations_from_route populates
#        both the combined `locations` string AND the new `location_
#        segments` list from a route approved with this exact phrasing ---
state = {
    # approved_text sits directly on trip_planning, never nested under
    # trip_planning.details - matching the real shape _run_chat_turn_engine
    # writes it in (plan = dict(trip_update["trip_planning"]); plan[
    # "approved_text"] = ...). The nested shape this fixture used before
    # (Shaked's PR #81 review, found via an identical path mistake in
    # _route_summary_line) meant this test's OWN fixture never matched
    # production, so _resolve_lodging_locations_from_route's real path bug
    # (fixed in the function itself) went uncaught here too.
    "trip_planning": {
        "approved_text": intro_text,
        "details": {"route": [{"base": "לרנקה"}, {"base": "פאפוס"}, {"base": "לימסול"}]},
    },
    "lodging": {"details": {"locations": None}},
    "dates": {"departure": "2026-12-06", "return": "2026-12-12"},
}
resolved = chat._resolve_lodging_locations_from_route(state)
lodging_details = resolved["lodging"]["details"]
check("locations string still gets the combined area list (backward compatible)",
      lodging_details["locations"] == "לרנקה, פאפוס, לימסול")
check("location_segments gets the full per-stop date breakdown",
      lodging_details["location_segments"] == ranges)

# --- 6. Regression guard: a route with NO intro-summary phrasing still
#        resolves the plain `locations` string exactly as before (qa-s84
#        behavior unaffected), just without location_segments ---
state_no_intro = {
    "trip_planning": {
        "approved_text": "לינה באזור לרנקה, לינה בפאפוס. מתאים לך המסלול?",
        "details": {"route": [{"base": "לרנקה"}, {"base": "פאפוס"}]},
    },
    "lodging": {"details": {"locations": None}},
    "dates": {"departure": "2026-12-06", "return": "2026-12-11"},
}
resolved_no_intro = chat._resolve_lodging_locations_from_route(state_no_intro)
check("no intro-summary phrasing -> locations string still works, location_segments absent",
      resolved_no_intro["lodging"]["details"]["locations"] == "לרנקה, פאפוס"
      and "location_segments" not in resolved_no_intro["lodging"]["details"])

# ============================================================
# Part 2: public_site.py's _run_lodging_search multi-segment behavior
# ============================================================
import public_site

fake_segment_calls = []


def fake_search_hotels(query, checkin_date, checkout_date, adults=1, children=0, children_ages=None, rooms=1,
                        min_price=None, max_price=None, vacation_rentals=False, min_hotel_class=None):
    fake_segment_calls.append({"query": query, "checkin_date": checkin_date, "checkout_date": checkout_date})
    return {"hotels": [{"name": f"Hotel in {query}", "price_per_night_ils": 100}]}


captured_answers = {}


def fake_save_trip_answers(trip_id, answers):
    captured_answers.clear()
    captured_answers.update(answers)


# --- 7. With location_segments present, one search fires per segment, and
#        each result is tagged with which stop it's for ---
answers_with_segments = {
    "destinations": "LCA,PFO",
    "departure_date": "2026-12-06", "return_date": "2026-12-12",
    "adults": 2, "children": 0, "lodging_rooms": 1,
    "lodging_location_segments": [
        {"location": "לרנקה", "date_from": "2026-12-06", "date_to": "2026-12-07"},
        {"location": "פאפוס", "date_from": "2026-12-07", "date_to": "2026-12-09"},
    ],
}
fake_segment_calls.clear()
with patch.object(public_site, "search_hotels", side_effect=fake_search_hotels), \
     patch.object(public_site, "_save_trip_answers", side_effect=fake_save_trip_answers):
    public_site._run_lodging_search(12345, answers_with_segments)
check("one search call fires per segment (2 segments -> 2 calls)", len(fake_segment_calls) == 2)
check("each segment call uses its own dates, not the trip's overall dates",
      fake_segment_calls[0]["checkin_date"] == "2026-12-06" and fake_segment_calls[0]["checkout_date"] == "2026-12-07"
      and fake_segment_calls[1]["checkin_date"] == "2026-12-07" and fake_segment_calls[1]["checkout_date"] == "2026-12-09")
check("each segment call queries its own location, not a single destination-derived city",
      {c["query"] for c in fake_segment_calls} == {"לרנקה", "פאפוס"})
check("results are tagged with which segment/stop they belong to",
      all(h.get("segment_location") in ("לרנקה", "פאפוס") for h in captured_answers.get("lodging_offers", []))
      and len(captured_answers.get("lodging_offers", [])) == 2)

# --- 8. Without location_segments, falls back to a single search, now
#        preferring lodging_location's first named area over the
#        destination-code-derived city (the qa-s89 root cause) ---
answers_no_segments = {
    "destinations": "LCA,PFO",
    "departure_date": "2026-12-06", "return_date": "2026-12-11",
    "adults": 2, "children": 0, "lodging_rooms": 1,
    "lodging_location": "פאפוס, לימסול",
}
fake_segment_calls.clear()
with patch.object(public_site, "search_hotels", side_effect=fake_search_hotels), \
     patch.object(public_site, "_save_trip_answers", side_effect=fake_save_trip_answers):
    public_site._run_lodging_search(12346, answers_no_segments)
check("no segments -> exactly one search call (unchanged single-search path)", len(fake_segment_calls) == 1)
check("the single search now prefers lodging_location's first area over destinations[0]-derived city",
      fake_segment_calls[0]["query"] == "פאפוס")

# --- 9. Neither segments nor lodging_location -> falls all the way back to
#        the original destination-code-derived city (regression guard) ---
answers_bare = {
    "destinations": "LCA,PFO",
    "departure_date": "2026-12-06", "return_date": "2026-12-11",
    "adults": 2, "children": 0, "lodging_rooms": 1,
}
fake_segment_calls.clear()
with patch.object(public_site, "search_hotels", side_effect=fake_search_hotels), \
     patch.object(public_site, "_save_trip_answers", side_effect=fake_save_trip_answers):
    public_site._run_lodging_search(12347, answers_bare)
check("no segments and no lodging_location -> still falls back to a destination-derived city, never crashes",
      len(fake_segment_calls) == 1 and bool(fake_segment_calls[0]["query"]))

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL LODGING PER-LOCATION SEGMENT TESTS PASSED")
