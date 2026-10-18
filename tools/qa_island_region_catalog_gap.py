"""QA for the island/region catalog gap Shlomo flagged right after PR #45
(relayed 2026-10-16): "סיציליה" (Sicily) - his own illustrative example for
that PR's reopen-gate country-match fix - turned out not to be recognized
as a destination AT ALL by the deterministic place-matching catalog, only
by the model's own free-text extraction. He asked to prioritize this list
next, after the Haifa-Eilat fix (PR #46): סיציליה, סרדיניה, כרתים, רודוס,
קורפו, מיורקה, טנריפה, קפריסין - noting כרתים and רודוס are Air Haifa's
own routes (HER, RHO), so this is directly tied to the Haifa feature too.

Of that list, "רודוס" (Rhodes), "קורפו" (Corfu) and "קפריסין" (Cyprus)
were ALREADY recognized - each already has its own airport entry (Rhodes,
Corfu) or is itself a country already in the catalog (Cyprus, via its
Larnaca/Paphos airports). The real, confirmed gap was exactly 5 names:
כרתים (Crete), סיציליה (Sicily), סרדיניה (Sardinia), מיורקה (Mallorca),
טנריפה (Tenerife) - each an island/region name that never appears as a
country_he or city_he value anywhere in static/airports.json, even though
every one of their airports is individually already in the catalog under
its own city name (Heraklion/Chania for Crete, Catania/Palermo for Sicily,
Cagliari/Olbia for Sardinia, Palma de Mallorca, Tenerife South).

This is the exact same shape of bug as the hallucination already seen live
and documented elsewhere in this codebase (_direct_route_hint_text's own
docstring): Ariella once stated as fact "לכרתים ברוב המקרים לא מגיעים
בטיסה ישירה מישראל" when a real seasonal direct route to Heraklion exists
- traceable to "כרתים" never being a recognized destination, so the real
route data behind it was never even reachable.

Root cause: _known_destination_names() and _resolve_destination_airports_
from_route_names() are both built/driven purely from the airport catalog's
own country_he/city_he fields (see _known_destination_names's own
docstring) - an island/region name isn't itself a country or a city, so it
was never recognized by design, not by oversight.

Fixed with a new, explicit `_ISLAND_REGION_GATEWAY_AIRPORTS` mapping
(island/region Hebrew name -> list of EVERY one of its own airports
already in the catalog, never just one), consumed in two places:
1. _known_destination_names() - the region name itself becomes a known
   destination (kept as-is in destination.places, never rewritten to one
   arbitrary city - unlike a spelling alias, picking a single city here
   would silently drop the island's other gateway).
2. _resolve_destination_airports_from_route_names() - a new resolution
   tier between the existing city-exact tier and the generic country
   substring-fallback tier, returning every one of the region's own
   airports (e.g. Crete -> both HER and CHQ, Sicily -> both CTA and PMO).

Run: python3 tools/qa_island_region_catalog_gap.py
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


AIRPORTS = _load_airports()

# --- The 5 confirmed gaps: recognized as a destination, kept as the
#     island/region name itself (not rewritten to one city) ---
check("'כרתים' (Crete) recognized as a destination", places_of("רוצה לטוס לכרתים") == ["כרתים"])
check("'סיציליה' (Sicily) recognized as a destination", places_of("רוצה חופשה בסיציליה") == ["סיציליה"])
check("'סרדיניה' (Sardinia) recognized as a destination", places_of("טסים לסרדיניה") == ["סרדיניה"])
check("'מיורקה' (Mallorca) recognized as a destination", places_of("טיסה למיורקה") == ["מיורקה"])
check("'טנריפה' (Tenerife) recognized as a destination", places_of("טיסה לטנריפה") == ["טנריפה"])

# --- Each resolves to EVERY one of its own gateways, not just one
#     (the over-narrowing mistake an alias-to-single-city would make) ---
check("Crete resolves to both Heraklion AND Chania",
      set(chat._resolve_destination_airports_from_route_names(AIRPORTS, ["כרתים"])) == {"HER", "CHQ"})
check("Sicily resolves to both Catania AND Palermo",
      set(chat._resolve_destination_airports_from_route_names(AIRPORTS, ["סיציליה"])) == {"CTA", "PMO"})
check("Sardinia resolves to both Cagliari AND Olbia",
      set(chat._resolve_destination_airports_from_route_names(AIRPORTS, ["סרדיניה"])) == {"CAG", "OLB"})
check("Mallorca resolves to Palma de Mallorca",
      chat._resolve_destination_airports_from_route_names(AIRPORTS, ["מיורקה"]) == ["PMI"])
check("Tenerife resolves to Tenerife South",
      chat._resolve_destination_airports_from_route_names(AIRPORTS, ["טנריפה"]) == ["TFS"])

# --- A specific island beats a bare country mentioned in the same message,
#     matching the existing precedence rule (see _known_destination_names's
#     own "specific place always beats a bare country name" comment) ---
check("'כרתים שביוון' -> Crete, not Greece",
      places_of("רוצה לנסוע לכרתים שביוון") == ["כרתים"])
check("'חופשה ביוון, אולי כרתים' -> Crete, not Greece",
      places_of("חופשה ביוון, אולי כרתים") == ["כרתים"])
check("a bare country mention alone is untouched: 'טיסה ליוון' -> Greece",
      places_of("טיסה ליוון") == ["יוון"])

# --- Already-working names on Shlomo's list stay working (no regression) ---
check("'רודוס' (Rhodes) was already recognized, still works",
      places_of("אני רוצה לטוס מחיפה לרודוס") == ["רודוס"])
check("'קורפו' (Corfu) was already recognized, still works",
      places_of("טיסה לקורפו") == ["קורפו"])
check("'קפריסין' (Cyprus) was already recognized, still works",
      places_of("חופשה חדשה לקפריסין") == ["קפריסין"])

# --- Crete and Rhodes are Air Haifa's own routes (per Shlomo) - confirm the
#     route-note chain reaches them correctly now that the destination is
#     actually recognized ---
check("hfa_routes.py reports Crete as a served Air Haifa route",
      hfa_routes.hfa_route_check(["כרתים"]) == "served")
note = chat._hfa_route_note({
    "departure_airport": "HFA",
    "destination_airports": ["HER", "CHQ"],
    "destination": {"places": ["כרתים"]},
})
check("_hfa_route_note confirms the Haifa->Crete route for a HFA departure",
      "כרתים" in note and "Air Haifa" in note and "אין טיסה" not in note)

# --- Regression guard: the round-5 Haifa/Tel-Aviv origin-vs-destination
#     fix (PR #39, already on main) must keep working after this change.
#     (The separate Eilat airport-catalog fix, PR #46, isn't assumed merged
#     here - this PR is independent of it and stands on its own against
#     main either way.) ---
check("'טיסה מחיפה לרומא...' still -> Rome, not Haifa (PR #39 regression guard)",
      places_of("טיסה מחיפה לרומא, 10 עד 14 בנובמבר, שני מבוגרים") == ["רומא"])

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL ISLAND/REGION CATALOG GAP TESTS PASSED")
