"""QA for a round-4 bug Shaked found (C2, Saalbach) that the business
owner separately reported for Bansko too: a ski trip's lodging search
returned results anchored to the GATEWAY AIRPORT'S OWN CITY (e.g.
"Privatzimmer in München", "Wohnung im Herzen Münchens") instead of the
actual ski resort (Saalbach) the customer is staying at.

Root cause: a ski trip's destination_airports deliberately holds GATEWAY
codes (MUC, SZG, INN, GVA...) that are often a different city entirely
from the resort itself (see _resolve_ski_destination_airports's own
docstring: "Vienna for Austria, instead of Innsbruck/Salzburg/Munich").
_run_lodging_search's single-search fallback used
_AIRPORT_LOCALIZATION[destination_codes[0]]'s own city as the lodging
query - which for a ski trip is the GATEWAY city, never the resort.

Fixed by preferring the already-resolved ski_resort_names (saved by
_resolve_ski_destination_airports) as the lodging search anchor whenever
the trip is a ski vacation and a resort name is actually known - falling
back to the old airport-city behavior only when no resort has been
pinned down yet (never crashes, never guesses).

Run: python3 tools/qa_ski_lodging_resort_not_gateway_city.py
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import public_site

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


captured = {}


def fake_search_hotels(query, checkin_date, checkout_date, adults=1, children=0, children_ages=None, rooms=1,
                        min_price=None, max_price=None, vacation_rentals=False, min_hotel_class=None):
    captured["query"] = query
    return {"hotels": [{"name": "Test Hotel", "hotel_class": 4, "price_per_night_ils": 200}]}


def fake_save_trip_answers(trip_id, answers):
    pass


# --- C2-style: Saalbach via Munich gateway must search Saalbach, not Munich ---
answers_saalbach = {
    "origin_airports": ["TLV"], "destinations": "MUC",
    "departure_date": "2027-01-20", "return_date": "2027-01-27",
    "adults": 2, "vacation_type": "ski",
    "ski_resort_names": ["Saalbach"], "ski_resort_names_he": ["זאלבאך"],
}
captured.clear()
with patch.object(public_site, "search_hotels", side_effect=fake_search_hotels), \
     patch.object(public_site, "_save_trip_answers", side_effect=fake_save_trip_answers):
    public_site._run_lodging_search(1, dict(answers_saalbach))
check("Saalbach (via Munich gateway) searches the resort, not the gateway city",
      captured.get("query") == "Saalbach")

# --- Business owner's own report: Bansko via Sofia gateway ---
answers_bansko = {
    "origin_airports": ["TLV"], "destinations": "SOF",
    "departure_date": "2027-02-10", "return_date": "2027-02-17",
    "adults": 2, "vacation_type": "ski",
    "ski_resort_names": ["Bansko"], "ski_resort_names_he": ["בנסקו"],
}
captured.clear()
with patch.object(public_site, "search_hotels", side_effect=fake_search_hotels), \
     patch.object(public_site, "_save_trip_answers", side_effect=fake_save_trip_answers):
    public_site._run_lodging_search(1, dict(answers_bansko))
check("Bansko (via Sofia gateway) searches the resort, not the gateway city",
      captured.get("query") == "Bansko")

# --- Regression guard: a standard (non-ski) trip must still use the
#     airport-derived city exactly as before ---
answers_standard = {
    "origin_airports": ["TLV"], "destinations": "FCO",
    "departure_date": "2027-01-20", "return_date": "2027-01-27",
    "adults": 2, "vacation_type": "standard",
}
captured.clear()
with patch.object(public_site, "search_hotels", side_effect=fake_search_hotels), \
     patch.object(public_site, "_save_trip_answers", side_effect=fake_save_trip_answers):
    public_site._run_lodging_search(1, dict(answers_standard))
check("a standard (non-ski) trip is unaffected - still searches the airport-derived city",
      captured.get("query") in ("Rome", "רומא"))

# --- Regression guard: a ski trip with no resort resolved yet must safely
#     fall back to the old airport-city behavior, never crash or guess ---
answers_ski_no_resort = {
    "origin_airports": ["TLV"], "destinations": "MUC",
    "departure_date": "2027-01-20", "return_date": "2027-01-27",
    "adults": 2, "vacation_type": "ski", "ski_resort_names": [],
}
captured.clear()
with patch.object(public_site, "search_hotels", side_effect=fake_search_hotels), \
     patch.object(public_site, "_save_trip_answers", side_effect=fake_save_trip_answers):
    public_site._run_lodging_search(1, dict(answers_ski_no_resort))
check("a ski trip with no resort resolved yet safely falls back to the airport city",
      captured.get("query") in ("Munich", "מינכן"))

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL SKI-LODGING-RESORT-NOT-GATEWAY-CITY TESTS PASSED")
