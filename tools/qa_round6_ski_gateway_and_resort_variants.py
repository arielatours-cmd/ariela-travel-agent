"""QA for three non-blocking "gaps for later" Shaked and the business owner
flagged after PR #42 shipped (round 6, 2026-10-16), all on the ski
gateway/resort resolution path (_resolve_ski_destination_airports).

1. _MOUNTAIN_GATEWAY_AIRPORTS only ever listed INN/GVA/SZG/TRN - so a
   confirmed ski trip naming Zurich, Munich, Sofia or Lyon directly as its
   gateway (Saalbach via Munich, Bansko via Sofia - the exact live cases
   from #42's own report) still got stuck exactly like the original
   Geneva regression #42 fixed, just for a different city. Fixed with a
   new, broader constant (_SKI_CATALOG_GATEWAY_AIRPORTS) derived directly
   from every gateway_airports entry in SKI_RESORTS - safe to widen here
   specifically because this fallback only ever runs once trip_type=="ski"
   is already an established fact, unlike the narrower
   _MOUNTAIN_GATEWAY_AIRPORTS (kept deliberately small to avoid
   misclassifying an ordinary Barcelona/Prague/Vienna city-break as a ski
   trip in a DIFFERENT, more sensitive context - _is_possible_ski_place).

2. The catalog lists Saalbach as "זלבאך", but the customer's own natural
   spelling ("זאלבאך", with an extra א, or the shorter "סלבך") never
   matched it at all - without a matched resort, _resolve_ski_destination_
   airports falls all the way through to the gateway-city fallback (or
   nothing), and the business owner's real report showed lodging search
   falling back to Munich because of exactly this mismatch. Same class of
   bug as the existing Val Thorens ("ואל טורנס"/"ואל תורנס") variant fix -
   added the same normalization for Saalbach.

Run: python3 tools/qa_round6_ski_gateway_and_resort_variants.py
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


def resolve(place):
    state = {"trip_type": "ski", "destination": {"places": [place], "mode": "specific", "status": "known"}}
    return chat._resolve_ski_destination_airports(state)


# --- 1. Previously-stuck gateway cities now resolve ---
check("Zurich resolves to ZRH as a direct ski gateway", resolve("ציריך").get("destination_airports") == ["ZRH"])
check("Munich resolves to MUC as a direct ski gateway", resolve("מינכן").get("destination_airports") == ["MUC"])
check("Sofia resolves to SOF as a direct ski gateway (Bansko's gateway)", resolve("סופיה").get("destination_airports") == ["SOF"])
check("Lyon resolves to LYS as a direct ski gateway", resolve("ליון").get("destination_airports") == ["LYS"])

# --- 2. Saalbach spelling variants ---
for variant in ("זאלבאך", "סלבך", "זלבאך"):
    r = resolve(variant)
    check(f"Saalbach variant '{variant}' resolves via the resort catalog (not just the empty gateway fallback)",
          (r.get("ski") or {}).get("resort_names") == ["Saalbach"])

# --- Regression guard: the narrower _is_possible_ski_place heuristic
#     (a DIFFERENT, more sensitive context - guessing trip_type from a
#     bare place name with no other signal) must still never misclassify
#     an ordinary Barcelona/Zurich city mention as a ski trip ---
check("Barcelona is still never guessed as a ski trip by the narrow heuristic",
      not chat._is_possible_ski_place("ברצלונה"))
check("Zurich is still never guessed as a ski trip by the narrow heuristic either (city-break risk)",
      not chat._is_possible_ski_place("ציריך"))

# --- Regression guard: Geneva (the original #42 fix) and an explicit
#     airport code must still both resolve correctly ---
check("Geneva still resolves to GVA (the original #42 fix)", resolve("ז'נבה").get("destination_airports") == ["GVA"])
check("An explicit GVA code still resolves", resolve("GVA").get("destination_airports") == ["GVA"])

# --- Regression guard: a specific resort (Chamonix) must still resolve
#     via the resort catalog as before, never short-circuited by the
#     broader gateway fallback ---
r_resort = resolve("שאמוני")
check("A named specific resort (Chamonix) still resolves via the resort catalog, not the gateway fallback",
      bool(r_resort.get("destination_airports")) and bool((r_resort.get("ski") or {}).get("resort_names")))

# --- Regression guard: an unrelated city never falsely resolves ---
check("Tel Aviv never falsely resolves to a ski gateway", not resolve("תל אביב").get("destination_airports"))

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL ROUND6-SKI-GATEWAY-AND-RESORT-VARIANTS TESTS PASSED")
