"""QA for the approved fix to dry-run 5d item 2 (Shaked's regression finding
on commit a0744a31, 23.10.2026, and her follow-up finding on 6dbb3be0,
same day): _reresolve_ambiguous_fresh_destination's candidate loop.

Round 1 (a0744a31 -> 6dbb3be0): the loop used to try the preposition-
stripped form even after the full needle already had a decisive EXACT
catalog match, which could spuriously land the stripped form within
edit-distance 1 of two unrelated real cities - 24 real catalog cities
starting with ל/ב/מ were wrongly flagged as ambiguous this way (Miami,
Bergen, Belgrade, Boston, Bari, Malta, among others). Fixed by stopping
at the first candidate form that matched anything at all.

Round 2 (6dbb3be0, Shaked's static review): that fix was still too
narrow - when the customer's raw quote ALREADY includes a leading ל/ב
(e.g. "לדבלין"), the FULL form itself can land within edit-distance 1 of
two unrelated cities ("לדבלין" is near both "דבלין"/Dublin and
"לובלין"/Lublin) - the loop stopped there, on a near match, and never
reached the stripped form ("דבלין"), which has the real exact match. 18
catalog names with a leading ל/ב hit this. Fixed: an exact match on ANY
candidate form is checked first, across all forms, before any near-match
check runs - exact-anywhere always wins over near-somewhere-else.

Shlomo's explicit acceptance criteria for this fix (23.10.2026, extended
by Shaked's round-2 review to also cover the ל+name and ב+name forms,
which Shaked herself scanned):
  1. A test scanning the ENTIRE catalog (bare names, and with a leading
     ל or ב prepended) confirming zero false positives.
  2. Confirmation that "ברגם" (the original scenario E repro) still
     correctly resolves as a genuine 2-way ambiguity (Bergen/Bergamo).

Round 3 (23.10.2026, Shaked's dry-run 5e live finding on this branch -
destination_evidence missing entirely, "ברגמו"/BGY saved turn 0 with no
ambiguity question at all - Shlomo's approved change of approach):
destination_evidence was the SOLE source of candidates; when the
model's extraction omitted it, the whole structural signal never ran.
Fixed: scan the customer's own raw message directly (every 1-4
consecutive-Hebrew-word window, since 114/824 catalog names are multi-
word and some contain an internal geresh, e.g. "בניה לוקה"/Banja Luka,
"ג'ירונה"/Girona - a single-word tokenizer found a coincidental near-
miss on a WORD FRAGMENT of these before ever reaching the longer
window's real exact match, wrongly reverting 100% of them in this
file's own first attempt at this scan). Fixed: an exact match on ANY
word-window anywhere in the message is checked first, across the whole
message, before any near-match check runs.

This file drives the real function end-to-end (_reresolve_ambiguous_
fresh_destination itself, not a re-implementation of its logic) for
every check, so it exercises the exact mechanism in production.

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


def resolve_fresh(evidence_text):
    """Drives the real _reresolve_ambiguous_fresh_destination end-to-end:
    a fresh same-turn resolution to evidence_text, verbatim in the
    message. Returns the resulting trip_update."""
    prior_state = {"destination_airports": []}
    update = {
        "destination_airports": ["XXX"],
        "destination": {"places": [evidence_text], "mode": "specific", "status": "known"},
    }
    # Dry-run 5e (23.10.2026): the message is now scanned token-by-token
    # against the full catalog (Shlomo's approved E fix), so a short
    # message keeps this scan's runtime reasonable without weakening
    # coverage - the destination token itself is still exactly what gets
    # exercised either way.
    message = f"ל{evidence_text}"
    return chat._reresolve_ambiguous_fresh_destination(prior_state, update, evidence_text, message)


def is_reverted_to_ambiguous(result):
    """True when the fix reverted the fresh resolution (destination_
    airports emptied) - i.e. it judged evidence_text a genuine 2-way
    ambiguity, never a decisive single real city."""
    return result.get("destination_airports") == []


# =====================================================================
# Part 1 (Shlomo's criterion 1, extended per Shaked's round-2 scan
# methodology): scan the ENTIRE catalog (static + high-confidence
# extended, 824 distinct names) in THREE forms - bare, with a leading ל,
# and with a leading ב (Shaked explicitly scanned both prefixed forms).
# For every real catalog name in every form, resolving it fresh must
# never be reverted to a false 2-way ambiguity - the real city is always
# reachable via an exact match on some candidate form.
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

false_positives_bare = []
false_positives_lamed = []
false_positives_bet = []
for name in sorted(all_names):
    if is_reverted_to_ambiguous(resolve_fresh(name)):
        false_positives_bare.append(name)
    if is_reverted_to_ambiguous(resolve_fresh("ל" + name)):
        false_positives_lamed.append("ל" + name)
    if is_reverted_to_ambiguous(resolve_fresh("ב" + name)):
        false_positives_bet.append("ב" + name)

check(f"FIX round 1: zero bare catalog names wrongly reverted to a false ambiguity "
      f"(found {len(false_positives_bare)}: {false_positives_bare[:5]})",
      len(false_positives_bare) == 0)
check(f"FIX round 2: zero ל+name forms wrongly reverted to a false ambiguity "
      f"(found {len(false_positives_lamed)}: {false_positives_lamed[:5]})",
      len(false_positives_lamed) == 0)
check(f"FIX round 2: zero ב+name forms wrongly reverted to a false ambiguity "
      f"(found {len(false_positives_bet)}: {false_positives_bet[:5]})",
      len(false_positives_bet) == 0)

# Round 1's named regressions - each resolves decisively, not ambiguous.
for city in ["מיאמי", "ברגן", "בלגרד", "בוסטון", "בארי", "מלטה"]:
    check(f"FIX round 1 regression (Shaked-named): '{city}' resolves decisively, not ambiguous",
          not is_reverted_to_ambiguous(resolve_fresh(city)))

# Round 2's named regressions (Shaked, static review of 6dbb3be0) - each
# of these, with its real leading ל/ב already in the raw quote, must
# resolve decisively via its stripped form's exact match, not revert.
for quoted in ["לדבלין", "לאוסקה", "בורונה", "במקאו", "בדרי", "לגומה"]:
    check(f"FIX round 2 regression (Shaked-named): '{quoted}' resolves decisively, not ambiguous",
          not is_reverted_to_ambiguous(resolve_fresh(quoted)))


# =====================================================================
# Part 2 (Shlomo's criterion 2): the original scenario E repro - "ברגם"
# itself (NOT a real catalog name - genuinely, structurally ambiguous
# between two real cities) must still correctly surface as a 2-way match.
# =====================================================================
check("REGRESSION GUARD: 'ברגם' is not itself a real catalog name (confirms this is "
      "a genuine ambiguity case, not an exact-match case)",
      "ברגם" not in all_names)

bergam_result = resolve_fresh("ברגם")
check("REGRESSION GUARD: 'ברגם' resolved fresh IS correctly reverted to an unresolved, "
      "named-but-ambiguous destination",
      is_reverted_to_ambiguous(bergam_result))
check("REGRESSION GUARD: 'ברגם' reverted destination.places carries the raw ambiguous "
      "needle itself (for _destination_gateway_answer_by_meaning to pick up)",
      bergam_result.get("destination", {}).get("places") == ["ברגם"])

# Confirm the actual 2-way candidate set via the underlying signal directly
# (the end-to-end function itself never exposes the candidate codes/cities
# - that naming happens later, in _destination_gateway_answer_by_meaning).
near_cities = chat._catalog_near_neighbor_cities("ברגם")
check("REGRESSION GUARD: 'ברגם' still correctly resolves to exactly {Bergen, Bergamo}",
      set(near_cities.keys()) == {"ברגן", "ברגמו"})


# =====================================================================
# Part 2b (round 3, Shaked's dry-run 5e live finding): no destination_
# evidence at all, scanning the raw message directly - the exact live
# failure shape (the model never supplied it). Also the multi-word/
# geresh names this round's fix specifically targets, bare and ל-
# prefixed, with NO destination_evidence supplied either.
# =====================================================================
def resolve_fresh_no_evidence(evidence_text):
    prior_state = {"destination_airports": []}
    update = {
        "destination_airports": ["XXX"],
        "destination": {"places": [evidence_text], "mode": "specific", "status": "known"},
    }
    message = f"ל{evidence_text}"
    return chat._reresolve_ambiguous_fresh_destination(prior_state, update, None, message)


check("round 3 FIX: 'ברגם' is still caught as ambiguous even with NO destination_evidence "
      "at all (the exact live failure shape - the model never supplied it)",
      is_reverted_to_ambiguous(resolve_fresh_no_evidence("ברגם")))

for multiword in ["בניה לוקה", "ג'ירונה", "בראץ'", "דה נאנג", "סאו טומה"]:
    check(f"round 3 FIX: multi-word/geresh catalog name '{multiword}' resolves decisively "
          f"with NO destination_evidence, even ל-prefixed",
          not is_reverted_to_ambiguous(resolve_fresh_no_evidence(multiword)))


# =====================================================================
# Part 3: unambiguous, non-prefixed fresh resolutions are left completely
# untouched (no catalog near-neighbor at all) - the baseline regression
# the earlier dryrun5d test file already covers, repeated here for this
# fix's own completeness.
# =====================================================================
for city in ["מדריד", "בוסטון", "מלטה"]:
    result = resolve_fresh(city)
    check(f"end-to-end: real city '{city}' resolved fresh this turn is NOT reverted",
          result.get("destination_airports") == ["XXX"])


if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print(f"\nALL DRYRUN5D-E-FIX-FULL-CATALOG-SCAN TESTS PASSED ({len(all_names)} catalog names scanned "
      f"in 3 forms each, 0 false positives)")
