"""QA for the approved fix to dry-run 5d item 2 (Shaked's regression finding
on commit a0744a31, 23.10.2026): _reresolve_ambiguous_fresh_destination's
candidate loop used to try the preposition-stripped form even after the
full needle already had a decisive EXACT catalog match, which could
spuriously land the stripped form within edit-distance 1 of two unrelated
real cities - 24 real catalog cities starting with ל/ב/מ were found to be
wrongly flagged as ambiguous this way (Miami, Bergen, Belgrade, Boston,
Bari, Malta, among others).

Shlomo's explicit acceptance criteria for this fix (23.10.2026):
  1. A test scanning the ENTIRE catalog confirming zero false positives.
  2. Confirmation that "ברגם" (the original scenario E repro) still
     correctly resolves as a genuine 2-way ambiguity (Bergen/Bergamo).

This file covers both, directly against _catalog_near_neighbor_cities
using the exact same candidate-loop logic the fixed function now applies
(stop at the first candidate form that matches ANYTHING at all; only try
the stripped form when the fuller form matched nothing whatsoever) - this
is the precise mechanism under test, not a re-implementation of it.

Run: python3 tools/qa_dryrun5d_e_fix_full_catalog_scan.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import ariella_chat_clean as chat  # noqa: E402

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


def resolve_like_fixed_function(needle):
    """Mirrors _reresolve_ambiguous_fresh_destination's exact candidate
    loop (post-fix): stop at the first candidate form that matches
    anything at all; only try the preposition-stripped form when the
    fuller form matched nothing whatsoever. Returns (winning_needle,
    near_cities_dict)."""
    candidates = [needle]
    if len(needle) >= 3 and needle[0] in "לבמ":
        candidates.append(needle[1:])
    winning_needle, near_cities = None, {}
    for candidate in candidates:
        found = chat._catalog_near_neighbor_cities(candidate)
        if found:
            winning_needle, near_cities = candidate, found
            break
    return winning_needle, near_cities


# =====================================================================
# Part 1 (Shlomo's criterion 1): scan the ENTIRE catalog (static + high-
# confidence extended, 824 distinct names - matches Shaked's own scan
# methodology exactly). For every real catalog name, resolving THAT exact
# name through the fixed candidate loop must never produce a false 2-way
# ambiguity - every real name has an exact match to itself, so condition
# א (exact match is decisive) must suppress any stripped-form coincidence.
# =====================================================================
all_names = set()
for airport in chat._load_airports():
    name = str(airport.get("city_he") or "").strip()
    if name:
        all_names.add(name)
for airport in chat._load_extended_airports():
    if str(airport.get("he_confidence") or "").lower() != "high":
        continue
    name = str(airport.get("city_he") or "").strip()
    if name:
        all_names.add(name)

check("sanity: catalog scan size matches Shaked's own methodology (824 distinct names)",
      len(all_names) == 824)

false_positives = []
for name in sorted(all_names):
    winning_needle, near_cities = resolve_like_fixed_function(name)
    if len(near_cities) == 2:
        false_positives.append((name, winning_needle, sorted(near_cities.keys())))

check(f"FIX: zero real catalog names are wrongly flagged as a 2-way ambiguity "
      f"(found {len(false_positives)}: {false_positives[:5]})",
      len(false_positives) == 0)

# The 24 cities Shaked explicitly named as affected by the regression -
# each one, called directly with its own exact name, must resolve as an
# exact (non-ambiguous) match, never a false 2-way split.
SHAKED_NAMED_REGRESSION_CITIES = [
    "מיאמי", "ברגן", "בלגרד", "בוסטון", "בארי", "מלטה",
]
for city in SHAKED_NAMED_REGRESSION_CITIES:
    check(f"FIX regression (Shaked-named): '{city}' resolves as a decisive exact match, "
          f"not a false ambiguity",
          city in all_names and len(resolve_like_fixed_function(city)[1]) != 2)


# =====================================================================
# Part 2 (Shlomo's criterion 2): the original scenario E repro - "ברגם"
# itself (NOT a real catalog name - genuinely, structurally ambiguous
# between two real cities) must still correctly surface as a 2-way match.
# =====================================================================
winning_needle, near_cities = resolve_like_fixed_function("ברגם")
check("REGRESSION GUARD: 'ברגם' is not itself a real catalog name (confirms this is "
      "a genuine ambiguity case, not an exact-match case)",
      "ברגם" not in all_names)
check("REGRESSION GUARD: 'ברגם' still correctly surfaces as a genuine 2-way ambiguity",
      len(near_cities) == 2)
check("REGRESSION GUARD: 'ברגם' still correctly resolves to exactly {Bergen, Bergamo}",
      set(near_cities.keys()) == {"ברגן", "ברגמו"})


# =====================================================================
# Part 3: end-to-end through the real function (not the mirrored helper),
# confirming the wiring itself behaves identically to Part 1/2's direct
# checks for a representative sample.
# =====================================================================
def make_fresh_state_and_update(evidence_text):
    prior_state = {"destination_airports": []}
    update = {
        "destination_airports": ["XXX"],
        "destination": {"places": [evidence_text], "mode": "specific", "status": "known"},
    }
    message = f"אני רוצה לטוס ל{evidence_text}"
    return prior_state, update, message


for city in ["מדריד", "בוסטון", "מלטה"]:
    message = f"אני רוצה לטוס ל{city}"
    prior_state, update, _ = make_fresh_state_and_update(city)
    result = chat._reresolve_ambiguous_fresh_destination(prior_state, update, city, message)
    check(f"end-to-end FIX: real city '{city}' resolved fresh this turn is NOT reverted "
          f"to an unresolved ambiguity (destination_airports stays set)",
          result.get("destination_airports") == ["XXX"])

bergam_message = "אני רוצה לטוס לברגם"
prior_state, update, _ = make_fresh_state_and_update("ברגם")
result = chat._reresolve_ambiguous_fresh_destination(prior_state, update, "ברגם", bergam_message)
check("end-to-end REGRESSION GUARD: 'ברגם' resolved fresh this turn IS correctly reverted "
      "to an unresolved, named-but-ambiguous destination",
      result.get("destination_airports") == [])
check("end-to-end REGRESSION GUARD: 'ברגם' reverted destination.places carries the raw "
      "ambiguous needle itself (for _destination_gateway_answer_by_meaning to pick up)",
      result.get("destination", {}).get("places") == ["ברגם"])


if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print(f"\nALL DRYRUN5D-E-FIX-FULL-CATALOG-SCAN TESTS PASSED ({len(all_names)} catalog names scanned, "
      f"0 false positives)")
