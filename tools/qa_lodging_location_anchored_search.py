"""QA for the critical (🔴🔴) bug from Shaked's round-14 QA run (2026-10-14,
qa/reports/2026-10-14-round14.md on the shaked branch, scenario C2 - Bansko
ski trip): the lodging results tab showed apartments in Jordan and Israel
("Sendebad chalet... in Dead Sea", "Sola Residences" near Jordan's King
Hussein/Aqaba airport, apartments in Amman, a Tel Aviv listing) - none in
Bansko at all.

Root cause traced in two places, both fixed here:

1. ariella_chat_clean._deterministic_lodging_facts: a combined customer
   answer like "דירה לארבעה, קרוב למעליות, עד 800 ללילה" (room type +
   location + budget bundled in one comma-separated message) stored the
   WHOLE sentence as lodging.details.locations, not just the location
   clause.

2. public_site._run_lodging_search: lodging_location (built from #1 above)
   was used as the ENTIRE hotel-search query in place of the destination
   city, instead of narrowing WITHIN it - so a value like "דירה לארבעה"
   (apartment for four) or "קרוב למעליות" (near the lifts) became a
   free-text query with zero geographic anchor, and the search API
   returned whatever happened to match, from anywhere in the world.

Run: python3 tools/qa_lodging_location_anchored_search.py
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

import ariella_chat_clean as chat
import public_site

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# --- 1. Extraction: the exact live Bansko message must yield a clean
#        location clause, not the whole sentence ---
bansko_msg = "דירה לארבעה, קרוב למעליות, עד 800 ללילה"
extracted = chat._deterministic_lodging_facts(bansko_msg, [])
locations = (extracted.get("lodging") or {}).get("details", {}).get("locations")
check("the room-type and budget clauses are stripped out of locations",
      locations == "קרוב למעליות")
check("the full raw sentence is never stored verbatim as locations",
      locations != bansko_msg)

# --- 2. Extraction: the original single-clause volunteered-preference
#        case (no comma) must still work exactly as before ---
single_clause = "קרוב להגיע לאתר סקי ללא רכב"
extracted2 = chat._deterministic_lodging_facts(single_clause, [])
check("a single-clause location-only message is preserved unchanged",
      extracted2.get("lodging", {}).get("details", {}).get("locations") == single_clause)


def _fake_search_hotels(query, checkin_date, checkout_date, adults=1, children=0, children_ages=None, rooms=1, max_price=None, vacation_rentals=False, min_hotel_class=None):
    _fake_search_hotels.last_query = query
    return {"hotels": []}


# --- 3. Search anchoring: even a location string with NO destination
#        mention at all must still produce a query anchored to the real
#        destination city, never standing alone ---
answers_bansko = {
    "origin_airports": ["TLV"], "destinations": "SOF",
    "departure_date": "2027-02-10", "return_date": "2027-02-17",
    "adults": 2, "lodging_location": "קרוב למעליות",
}
with patch.object(public_site, "search_hotels", side_effect=_fake_search_hotels):
    public_site._run_lodging_search(99999001, dict(answers_bansko))
check("the search query is anchored to the real destination city",
      "Sofia" in _fake_search_hotels.last_query)
check("the area preference is still included alongside the destination",
      "קרוב למעליות" in _fake_search_hotels.last_query)

# --- 4. Search anchoring: the EXACT pre-fix failure mode - a room-type
#        string leaking into lodging_location with no cleanup - must still
#        never become a destination-less query (defense in depth, in case
#        extraction is ever bypassed e.g. by a direct API caller) ---
answers_unclean = dict(answers_bansko)
answers_unclean["lodging_location"] = "דירה לארבעה"
with patch.object(public_site, "search_hotels", side_effect=_fake_search_hotels):
    public_site._run_lodging_search(99999002, answers_unclean)
check("even an unclean location value still gets the real destination city appended",
      "Sofia" in _fake_search_hotels.last_query)

# --- 5. No lodging_location at all -> falls back cleanly to just the
#        destination city, never crashes ---
answers_none = dict(answers_bansko)
answers_none.pop("lodging_location", None)
with patch.object(public_site, "search_hotels", side_effect=_fake_search_hotels):
    public_site._run_lodging_search(99999003, answers_none)
check("no lodging_location at all falls back to the destination city alone",
      _fake_search_hotels.last_query == "Sofia")

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL LODGING-LOCATION-ANCHORED-SEARCH TESTS PASSED")
