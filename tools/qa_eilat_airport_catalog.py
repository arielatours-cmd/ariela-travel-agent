"""QA for the next blocker in Shaked's round-7 findings (qa-s96,
2026-10-16): "טיסה מחיפה לאילת" (flight from Haifa to Eilat) returned no
destination at all (_deterministic_destination_facts -> {}), even though
ETM/Eilat-Ramon is Air Haifa's own central/flagship domestic route
(data/hfa_routes.json already lists it as "confirmed", verified 2026-10-16).

Root cause: Eilat was never in static/airports.json at all - only TLV and
HFA exist for Israel there. Every deterministic place-recognition helper
in ariella_chat_clean.py (_known_place_names, _known_destination_names,
and therefore _mentioned_places, _deterministic_destination_facts, and
destination-airport resolution) is built directly from that airport
catalog (travel_agents._load_airports), by design - see
_known_destination_names()'s own docstring ("every real, supported
destination is recognized automatically, with no separate list to
remember to keep in sync"). So Eilat wasn't a recognition-logic bug at
all; it was a missing catalog entry, silently dropping the destination
for the entire conversation exactly like the Cyprus gap that same
docstring describes, and like the Sicily/region-catalog gap found while
fixing PR #45 (still open, separate issue).

Fixed by adding an ETM (Ramon Airport, Eilat) entry to
static/airports.json, right after HFA, matching the existing per-airport
shape (code/city_en/city_he/name_en/name_he/country/country_en/country_he).
This is a pure data addition - no code changes - so it automatically
flows through the whole existing recognition + airport-resolution chain,
and through the existing Air Haifa route-note logic in _hfa_route_note
(which already had ETM listed in data/hfa_routes.json as a confirmed,
non-seasonal route).

These are the same 2 cases added to qa/cases.json
(dest-tisa-me-haifa-le-eilat, dest-eilat-alone-recognized) - this file
re-asserts them directly plus the full Haifa->Eilat chain end to end
(destination recognition -> destination_airports resolution -> the Air
Haifa route-note wording), and guards that Haifa's existing
international destinations (round-5/PR#39 fix) and the full airport
catalog still parse and resolve correctly - this file touches
static/airports.json, the most widely shared catalog in the codebase.

Run: python3 tools/qa_eilat_airport_catalog.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import ariella_chat_clean as chat
from travel_agents import _load_airports
import hfa_routes

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


def places_of(message):
    result = chat._deterministic_destination_facts([], message, {})
    return (result.get("destination") or {}).get("places")


# --- Shaked's exact live reproduction (qa-s96) ---
check("'טיסה מחיפה לאילת' -> Eilat, not empty (was {} before the fix)",
      places_of("טיסה מחיפה לאילת") == ["אילת"])
check("'טיסה לאילת' (no origin stated) also recognized",
      places_of("טיסה לאילת") == ["אילת"])

# --- Eilat is now in the real catalogs the recognition chain is built from ---
check("Eilat/ETM present in static/airports.json",
      any(str(a.get("code") or "").upper() == "ETM" for a in _load_airports()))
check("'אילת' is a known destination name (_known_destination_names)",
      "אילת" in chat._known_destination_names())
check("'אילת' is a known place name (_known_place_names)",
      "אילת" in chat._known_place_names())

# --- Full chain: destination mention -> resolved airport code ---
codes = chat._resolve_destination_airports_from_route_names(_load_airports(), ["אילת"])
check("'אילת' resolves to airport code ETM", codes == ["ETM"])

# --- The Air Haifa route-note already knew ETM was a confirmed domestic
#     route (data/hfa_routes.json) - now that the destination actually
#     reaches that code path, confirm the note fires correctly end to end ---
check("hfa_routes.py reports Eilat as a served Air Haifa route",
      hfa_routes.hfa_route_check(["אילת"]) == "served")
note = chat._hfa_route_note({
    "departure_airport": "HFA",
    "destination_airports": ["ETM"],
    "destination": {"places": ["אילת"]},
})
check("_hfa_route_note confirms the Haifa->Eilat route for a HFA departure",
      "אילת" in note and "Air Haifa" in note and "אין טיסה" not in note)

# --- Regressions: the round-5 Haifa/Tel-Aviv origin-vs-destination fix
#     (PR #39) must keep working after this catalog change ---
check("'טיסה מחיפה לרומא...' still -> Rome, not Haifa (PR #39 regression guard)",
      places_of("טיסה מחיפה לרומא, 10 עד 14 בנובמבר, שני מבוגרים") == ["רומא"])
check("'אני רוצה לטוס מחיפה לרודוס' still -> Rhodes (PR #39 regression guard)",
      places_of("אני רוצה לטוס מחיפה לרודוס") == ["רודוס"])

# --- The whole airport catalog must still be well-formed after the edit ---
airports = _load_airports()
check("airport catalog still parses and every entry has a code",
      len(airports) >= 189 and all(str(a.get("code") or "").strip() for a in airports))
check("no duplicate airport codes were introduced",
      len([a.get("code") for a in airports]) == len(set(a.get("code") for a in airports)))

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL EILAT AIRPORT CATALOG TESTS PASSED")
