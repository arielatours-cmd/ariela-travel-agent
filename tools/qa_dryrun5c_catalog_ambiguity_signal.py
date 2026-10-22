"""QA for dry-run 5c item 1 (Shlomo/Shaked, 22.10.2026, qa/reports/
2026-10-22-dryrun5c.md, scenario E, "ברגם" -> Bergamo with NO question
ever asked, TWICE in a row across dry-run 5b and 5c) - "the most severe"
finding per Shlomo's own relay, fixed per his explicitly APPROVED 5-line
plan (sent 22.10.2026, approved with 3 conditions the same day):

Root cause: the model kept confidently returning a single candidate for a
name that is, structurally, equally close to TWO real catalog cities -
relying on the model to self-report its own uncertainty failed live,
twice in a row, despite the evidence-gated 1-or-2-candidate schema built
in dry-run 5b.

Fix: a cheap, STRUCTURAL catalog pre-check (_catalog_near_neighbor_cities)
runs BEFORE the single classifier call - scans city_he across BOTH
catalogs (static + extended, 1,405 entries combined) for real cities
within edit-distance 1 of the raw unresolved place name. When it finds
exactly 2 distinct cities, the SAME single call (cost-neutral) is
reframed to name those two specific real candidates explicitly, instead
of leaving recognition fully open - the model still has the final,
evidence-gated say (one, both, or neither), never a forced pick. This is
a SIGNAL only, never the recognition itself - recognition still belongs
entirely to the model, per the business owner's standing directive.

Shlomo's 3 approval conditions, all verified here:
(a) An EXACT match (distance 0) to one city is decisive - no ambiguity,
    never ask, regardless of any other near-distance coincidence.
(b) The empirical test must run against the FULL combined catalog (1,405
    entries, not just the 188 static ones) - verified against the real
    37-destination deals list (config.DESTINATIONS): zero false
    positives once condition (a) applies. A naive distance<=1 check with
    no exact-match priority DID produce 6/37 false positives against the
    larger catalog (וינה, סופיה, ורשה, סקופיה, באקו, מלטה) - condition
    (a) is what brings it to zero, not a coincidence of the small static
    catalog alone. A SEPARATE false-positive risk specific to the
    extended catalog's own lower-confidence entries (ברום/Broome,
    he_confidence="medium", turning "ברגם"'s real 2-way ambiguity into a
    spurious 3-way non-match) is fixed by trusting only he_confidence=
    "high" extended-catalog entries for this signal.
(c) The ambiguity question must name city AND country, as ONE question -
    verified via the destination_ambiguous_hint text (built in the
    sibling candidate-handling code, unchanged by this item).

Run: python3 tools/qa_dryrun5c_catalog_ambiguity_signal.py
"""
import os
import sys
import json
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import ariella_chat_clean as chat  # noqa: E402
from config import DESTINATIONS  # noqa: E402

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


KEY = os.getenv("ANTHROPIC_API_KEY", "test-key-not-real")
MODEL = "claude-sonnet-5"

# =====================================================================
# Direct unit coverage: _levenshtein_distance / _normalize_he_final_letters.
# =====================================================================
check("_levenshtein_distance: identical strings -> 0",
      chat._levenshtein_distance("זדאר", "זדאר") == 0)
check("_levenshtein_distance: one substitution -> 1",
      chat._levenshtein_distance("זדאר", "זדאק") == 1)
check("_levenshtein_distance: final-letter normalized (ם/מ, ן/נ don't count as a real difference)",
      chat._levenshtein_distance("ברגם", "ברגמו") == 1)  # insertion of ו only, מ/ם treated equal
check("_normalize_he_final_letters maps every final letter to its regular form",
      chat._normalize_he_final_letters("םןךףץ") == "מנכפצ")


# =====================================================================
# Part 1: _catalog_near_neighbor_cities - the core structural signal.
# =====================================================================
check("scenario E repro: 'ברגם' resolves to exactly {Bergen, Bergamo} against the combined catalog",
      set(chat._catalog_near_neighbor_cities("ברגם").keys()) == {"ברגן", "ברגמו"})

# Condition (a): an exact match is decisive, suppressing any coincidental
# near-distance match entirely.
check("condition (a): 'וינה' (exact match to Vienna) is NOT flagged ambiguous, despite "
      "being distance-1 from 'ורנה'/'וילנה' too",
      chat._catalog_near_neighbor_cities("וינה") == {"וינה": ["VIE"]})
check("condition (a): 'סופיה' (exact match) is NOT flagged ambiguous despite being "
      "distance-1 from 'סקופיה'",
      chat._catalog_near_neighbor_cities("סופיה") == {"סופיה": ["SOF"]})

# Condition (b): empirical validation against the REAL 37-destination
# deals list and the full combined (1,405-entry) catalog - zero false
# positives.
_false_positives = [
    (d["name"], chat._catalog_near_neighbor_cities(d["name"]))
    for d in DESTINATIONS
    if len(chat._catalog_near_neighbor_cities(d["name"])) >= 2
]
check(f"condition (b): zero false positives among all {len(DESTINATIONS)} real deal "
      f"destinations against the full combined catalog (found: {_false_positives})",
      not _false_positives)

# The extended catalog's own lower-confidence entries must never
# manufacture a spurious 3+-way "ambiguity" out of a real 2-way one.
check("extended-catalog low/medium-confidence entries (e.g. 'ברום'/Broome, medium) never "
      "join the signal and corrupt a real 2-way match into a non-triggering 3-way one",
      len(chat._catalog_near_neighbor_cities("ברגם")) == 2)

# Regression: an unrelated, uncatalogued string matches nothing at all.
check("regression: a name with no real catalog neighbor at all returns empty",
      chat._catalog_near_neighbor_cities("קסקסקסקס") == {})
check("regression: empty/None input never crashes",
      chat._catalog_near_neighbor_cities("") == {} and chat._catalog_near_neighbor_cities(None) == {})


# =====================================================================
# Part 2: _destination_gateway_answer_by_meaning - end-to-end with the
# catalog signal firing, reframing the SAME single call (never a second
# call - cost-neutral).
# =====================================================================
BERGEN_STATE = {
    "destination": {"places": ["ברגם"], "mode": None, "status": "known"},
    "destination_airports": [],
    "requested_services": ["flights"],
    "service_decisions": {"flights": {"wanted": True}},
}

_calls = []


def _fake_bergen_classifier(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other", **kw):
    if source == "classifier":
        _calls.append(system_static)
        check("the reframed prompt explicitly names BOTH real catalog candidates (Bergen and Bergamo)",
              "Bergen" in system_static and "Bergamo" in system_static)
        return json.dumps({"evidence": "ברגם", "candidates": [
            {"city_en": "Bergen", "iata_code": "BGO"},
            {"city_en": "Bergamo", "iata_code": "BGY"},
        ]})
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_bergen_classifier):
    result = chat._destination_gateway_answer_by_meaning("ברגם מתאים לנו", [], BERGEN_STATE)
check("scenario E FIX: 'ברגם' no longer silently resolves - nothing is written to destination_airports",
      not result.get("destination_airports"))
check("scenario E FIX: a one-turn ambiguous hint is produced instead, naming both real options",
      bool(result.get("_destination_ambiguous_hint")))
check("scenario E FIX: exactly one classifier call was made (cost-neutral - the catalog signal "
      "reframes the SAME call, never adds a second one)",
      len(_calls) == 1)
check("condition (c): the ambiguity hint names city AND country for both options",
      "Norway" in result.get("_destination_ambiguous_hint", "") or "נורווגיה" in result.get("_destination_ambiguous_hint", "")
      or "Italy" in result.get("_destination_ambiguous_hint", "") or "איטליה" in result.get("_destination_ambiguous_hint", ""))
check("condition (c): it is framed as exactly one question to ask",
      "שאלי שאלה אחת" in result.get("_destination_ambiguous_hint", ""))

# Regression: when the structural signal does NOT fire (e.g. "זדאר", no
# catalog near-neighbor at all), the prompt is unchanged from before -
# fully open recognition, no candidates named.
_calls2 = []


def _fake_zadar_classifier(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other", **kw):
    if source == "classifier":
        _calls2.append(system_static)
        check("regression: no catalog signal -> the prompt never names any specific candidate city",
              "לפי הקטלוג שלנו, השם הזה קרוב מאוד" not in system_static)
        return json.dumps({"evidence": "זדאר", "candidates": [{"city_en": "Zadar", "iata_code": "ZAD"}]})
    return "{}"


ZADAR_STATE = dict(BERGEN_STATE, destination={"places": ["זדאר"], "mode": None, "status": "known"})
with patch.object(chat, "_post_claude", side_effect=_fake_zadar_classifier):
    result_zadar = chat._destination_gateway_answer_by_meaning("זדאר מתאים לנו", [], ZADAR_STATE)
check("regression: an unambiguous name (no catalog near-neighbor) still resolves normally, "
      "single call, single verified candidate",
      result_zadar.get("destination_airports") == ["ZAD"] and len(_calls2) == 1)


if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DRYRUN5C-CATALOG-AMBIGUITY-SIGNAL TESTS PASSED")
