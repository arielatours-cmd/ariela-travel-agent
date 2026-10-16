"""QA for two round-4 bugs Shaked found (A2/Italy airports, C1/Geneva ski
regression, 2026-10-16), both diagnosed precisely in her full round-4
report (qa/reports/2026-10-16-round4.md on the shaked branch).

A2 (Italy): a bare country-level destination ("איטליה") resolves to every
airport in the catalog and gets cut to the first 4 in catalog order
(BGY, BLQ, CAG, CTA - none of them Milan or Venice). Once
destination_airports held ANY value, `_resolve_destination_airports_from_route`
unconditionally returned early and never re-derived it again - so when the
customer later explicitly said "לנחות במילאנו ולחזור מוונציה" (land in
Milan, return from Venice), Ariella told her "מילאנו וונציה אינם ברשימת
השדות שאני יכולה לחפש" even though both are perfectly real, known
airports. Fixed by only skipping the re-derivation when the current
places don't resolve to any genuine CITY-level match (a repeated bare
country mention is still correctly ignored - only a city name is specific
enough to override a broad guess).

C1 (Geneva, ski): `_resolve_ski_destination_airports` only ever matches
against the SKI_RESORTS catalog (resort name or country) - a GATEWAY CITY
named directly ("חופשת סקי, טיסה לז'נבה") is not a resort and barely ever
appears inside a resort's own country/resort string, so destination_airports
never got set at all - not even once the customer explicitly typed the
airport code itself ("הנחיתה בז'נבה GVA"). Ariella kept asking "באיזה שדה
תרצי לנחות?" forever. Fixed by falling back to a general-airport-catalog
city match (or an explicit 3-letter code) against the known mountain-
gateway airports (INN/GVA/SZG/TRN) when no resort-catalog match exists.

Run: python3 tools/qa_round4_italy_airports_and_geneva_ski_gateway.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import ariella_chat_clean as chat

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# --- A2: Italy, country-level guess must never block a later city update ---
state1 = {"destination": {"places": ["איטליה"], "mode": "country", "status": "known"}}
r1 = chat._resolve_destination_airports_from_route(state1)
check("turn 1 (country only) sets SOME broad Italy gateway set",
      bool(r1.get("destination_airports")))

state2 = dict(r1)
state2["destination"] = {"places": ["איטליה", "מילאנו", "ונציה"], "mode": "specific", "status": "known"}
r2 = chat._resolve_destination_airports_from_route(state2)
check("turn 2 (Milan/Venice explicitly named) updates to MXP/VCE, not stuck on the broad guess",
      set(r2.get("destination_airports") or []) == {"MXP", "VCE"})

# --- Regression guard: a repeated bare country mention (no city) must
#     still never clobber an already-resolved value with an equally
#     arbitrary guess - the original protection this early-return existed
#     for in the first place. ---
state3 = dict(r2)
state3["destination"] = {"places": ["איטליה"], "mode": "country", "status": "known"}
r3 = chat._resolve_destination_airports_from_route(state3)
check("a later bare country repeat does not clobber the already-resolved city-level codes",
      set(r3.get("destination_airports") or []) == {"MXP", "VCE"})

# --- C1: Geneva named directly as a ski gateway (no specific resort) ---
state_geneva = {"trip_type": "ski", "destination": {"places": ["ז'נבה"], "mode": "specific", "status": "known"}}
r_geneva = chat._resolve_ski_destination_airports(state_geneva)
check("Geneva named directly as a ski gateway resolves to GVA",
      r_geneva.get("destination_airports") == ["GVA"])

# --- Explicit airport code typed directly ("GVA") must also resolve ---
state_gva_code = {"trip_type": "ski", "destination": {"places": ["GVA"], "mode": "specific", "status": "known"}}
r_gva_code = chat._resolve_ski_destination_airports(state_gva_code)
check("an explicit 'GVA' code also resolves (customer typed the code itself)",
      r_gva_code.get("destination_airports") == ["GVA"])

# --- Regression guard: a named SPECIFIC RESORT must still resolve via the
#     resort catalog as before, never accidentally short-circuited by the
#     new gateway-city fallback ---
state_resort = {"trip_type": "ski", "destination": {"places": ["שאמוני"], "mode": "specific", "status": "known"}}
r_resort = chat._resolve_ski_destination_airports(state_resort)
check("a named specific resort (Chamonix) still resolves via the resort catalog as before",
      bool(r_resort.get("destination_airports")) and bool((r_resort.get("ski") or {}).get("resort_names")))

# --- Regression guard: a non-ski-related place name must still return no
#     match (the fallback must not over-match unrelated cities) ---
state_unrelated = {"trip_type": "ski", "destination": {"places": ["תל אביב"], "mode": "specific", "status": "known"}}
r_unrelated = chat._resolve_ski_destination_airports(state_unrelated)
check("an unrelated city (Tel Aviv) never falsely resolves to a mountain gateway",
      not r_unrelated.get("destination_airports"))

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL ROUND4-ITALY-AIRPORTS-AND-GENEVA-SKI-GATEWAY TESTS PASSED")
