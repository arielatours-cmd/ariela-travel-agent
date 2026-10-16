"""QA for a round-4 bug Shaked found (2026-10-16): a stated minimum
lodging comfort level ("4 כוכבים ומעלה") was captured as
lodging.details.level="יוקרתי" but never actually enforced anywhere in
the real search. Budapest came back only 4/10 results at 4-star+, and
Zurich returned a 3-star ibis, a hostel (MEININGER), and an
airport-adjacent Radisson despite the customer explicitly asking for
4-star+.

Fixed in two places:
  - scanner.py's search_hotels() now accepts min_hotel_class, passes it to
    SerpApi as the documented `hotel_class` filter param (e.g. "4,5" for
    4-star-and-up), AND re-checks every returned property's own
    hotel_class client-side before returning - never trusting the
    upstream filter alone to be exhaustive. A property with no resolvable
    hotel_class at all is excluded too (never silently assumed to pass).
  - public_site.py's _run_lodging_search() now maps lodging_level
    ("יוקרתי"->4, "בינוני"->3) to that parameter and passes it through on
    both the per-segment and single-search code paths. "בסיסי" states no
    floor at all - any class is a valid answer to "the cheapest option".

Run: python3 tools/qa_lodging_star_level_enforced.py
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import scanner

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


FAKE_PROPERTIES = {
    "properties": [
        {"name": "Luxury Hotel", "hotel_class": 5, "rate_per_night": {"extracted_lowest": 500}},
        {"name": "Nice 4 star", "hotel_class": 4, "rate_per_night": {"extracted_lowest": 300}},
        {"name": "Budget 3 star (ibis-like)", "hotel_class": 3, "rate_per_night": {"extracted_lowest": 150}},
        {"name": "Hostel (MEININGER-like), no class", "rate_per_night": {"extracted_lowest": 80}},
        {"name": "Airport Radisson, string class", "hotel_class": "4-star hotel", "rate_per_night": {"extracted_lowest": 350}},
    ]
}

captured_params = {}


def fake_request(params):
    captured_params.clear()
    captured_params.update(params)
    return FAKE_PROPERTIES


with patch.object(scanner, "_serpapi_request", side_effect=fake_request), patch.object(scanner, "_api_key", return_value="test-key"):
    # --- 4-star-and-up ("יוקרתי") ---
    result = scanner.search_hotels("Budapest", "2027-01-10", "2027-01-15", adults=2, min_hotel_class=4)
    names = [h["name"] for h in result["hotels"]]
    check("4-star-and-up request sends SerpApi's own hotel_class filter ('4,5')",
          captured_params.get("hotel_class") == "4,5")
    check("every returned hotel is 4-star or above, no 3-star/hostel/unclassed slipped through",
          names == ["Luxury Hotel", "Nice 4 star", "Airport Radisson, string class"])
    check("a hotel_class given as a descriptive string ('4-star hotel') is still correctly parsed and kept",
          "Airport Radisson, string class" in names)

    # --- no level stated at all: unfiltered, unchanged behavior ---
    result_unfiltered = scanner.search_hotels("Budapest", "2027-01-10", "2027-01-15", adults=2)
    check("no min_hotel_class -> no hotel_class param sent, all 5 properties still returned",
          "hotel_class" not in captured_params and len(result_unfiltered["hotels"]) == 5)

    # --- 3-star-and-up ("בינוני") ---
    result_3plus = scanner.search_hotels("Zurich", "2027-01-10", "2027-01-15", adults=2, min_hotel_class=3)
    names_3plus = [h["name"] for h in result_3plus["hotels"]]
    check("3-star-and-up keeps the budget 3-star option but still drops the unclassed hostel",
          "Budget 3 star (ibis-like)" in names_3plus and "Hostel (MEININGER-like), no class" not in names_3plus)

# --- public_site.py's level -> min_hotel_class mapping and wiring ---
import public_site

captured_calls = []


def fake_search_hotels(query, checkin_date, checkout_date, adults=1, children=0, children_ages=None, rooms=1,
                        min_price=None, max_price=None, vacation_rentals=False, min_hotel_class=None):
    captured_calls.append({"query": query, "min_hotel_class": min_hotel_class})
    return {"hotels": [{"name": f"Hotel in {query}", "hotel_class": 4, "price_per_night_ils": 300}]}


def fake_save_trip_answers(trip_id, answers):
    pass


answers_luxury = {
    "origin_airports": ["TLV"], "destinations": "BUD",
    "departure_date": "2027-03-10", "return_date": "2027-03-15",
    "adults": 2, "lodging_level": "יוקרתי",
}
captured_calls.clear()
with patch.object(public_site, "search_hotels", side_effect=fake_search_hotels), \
     patch.object(public_site, "_save_trip_answers", side_effect=fake_save_trip_answers):
    public_site._run_lodging_search(1, dict(answers_luxury))
check("lodging_level='יוקרתי' is translated into min_hotel_class=4 on the real search call",
      captured_calls and captured_calls[0]["min_hotel_class"] == 4)

answers_basic = dict(answers_luxury, lodging_level="בסיסי")
captured_calls.clear()
with patch.object(public_site, "search_hotels", side_effect=fake_search_hotels), \
     patch.object(public_site, "_save_trip_answers", side_effect=fake_save_trip_answers):
    public_site._run_lodging_search(1, dict(answers_basic))
check("lodging_level='בסיסי' (budget, no floor) sends no min_hotel_class at all",
      captured_calls and captured_calls[0]["min_hotel_class"] is None)

answers_no_level = dict(answers_luxury)
answers_no_level.pop("lodging_level")
captured_calls.clear()
with patch.object(public_site, "search_hotels", side_effect=fake_search_hotels), \
     patch.object(public_site, "_save_trip_answers", side_effect=fake_save_trip_answers):
    public_site._run_lodging_search(1, dict(answers_no_level))
check("no lodging_level stated at all -> no min_hotel_class, unchanged behavior",
      captured_calls and captured_calls[0]["min_hotel_class"] is None)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL LODGING-STAR-LEVEL-ENFORCED TESTS PASSED")
