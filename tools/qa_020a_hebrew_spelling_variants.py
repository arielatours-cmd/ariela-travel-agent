"""QA for task 020a (approved by the business owner 22.10.2026, relayed by
Shlomo, after dry-run 1's live miss - product/dev-tasks/020a-hebrew-
spelling-variants.md, ofek branch): a customer writing "וולנסיה" (double-
vav "ketiv male") wasn't recognized at all, even though the catalog knows
"ולנסיה" - _match_city_exact only ever did an exact string compare after
_normalize_place_name's whitespace/hyphen/quote stripping, with no notion
of common Hebrew spelling variation.

Fix: _normalize_he_spelling (comparison-only, never shown to the customer -
every display path still uses the catalog's own official name) layers two
more things on top of _normalize_place_name: collapsing a doubled ו/י down
to one, and mapping each of two confusable-letter groups (ט/ת, ק/כ/ך) to a
single representative. _match_city_exact uses this instead of the plain
normalize, so "וולנסיה"/"ולנסיה" compare equal while the function's own
exact-match (never substring) guarantee is untouched - the Heraklion/Lyon
lesson documented in its own docstring still holds regardless, since the
two names remain different lengths after normalization either way.

_known_destination_names() (the airport-catalog scan, cached) now also
warns - once, at load time - if two DIFFERENT real catalog names would
become indistinguishable under this same normalization, rather than
silently auto-picking one (spec item 7).

Deliberately NOT extended to the free-text/raw-message scan inside
_deterministic_destination_facts: a trial regex-based spelling-variant
matcher applied directly to continuous text caused a genuine false
positive this file's own earlier version (git history) caught live before
it ever shipped - Lyon's doubled-ו variant of "ליון" is letter-for-letter
identical to "ל" (to) + "יוון" (Greece), so "טסה מחיפה ליוון" (flying to
Greece) matched Lyon instead. _match_city_exact never has this problem
(it only ever compares an already-isolated candidate string, never a
running sentence), so the fix stays scoped there - flagged as a known
limitation for Ofek/Shlomo rather than widening this task with an unsafe
word-boundary workaround.

ש/ס and א/ע confusions are explicitly NOT part of this stage (per the dev
task itself) - test 3 documents that "בודפעשט" stays unrecognized on
purpose.

Run: python3 tools/qa_020a_hebrew_spelling_variants.py
"""
import os
import sys
import logging
from io import StringIO

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import ariella_chat_clean as chat
import travel_agents

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


AIRPORTS = travel_agents._load_airports()

# =====================================================================
# Test 1 (spec): "וולנסיה" resolves to VLC.
# =====================================================================
check("test 1: 'וולנסיה' (double-vav) resolves to VLC via _match_city_exact",
      chat._match_city_exact("וולנסיה", AIRPORTS) == "VLC")
check("test 1: the catalog's own 'ולנסיה' still resolves to VLC (no regression)",
      chat._match_city_exact("ולנסיה", AIRPORTS) == "VLC")

# =====================================================================
# Test 3 (spec): "בודפעשט" (ע/א confusion, out of scope this stage) is
# NOT recognized - documented, not fixed.
# =====================================================================
check("test 3: 'בודפעשט' is NOT recognized this stage (ש/ס and א/ע are "
      "explicitly out of scope per the dev task) - documents the "
      "limitation, doesn't fix it",
      chat._match_city_exact("בודפעשט", AIRPORTS) is None)

# =====================================================================
# Test 4 (spec): "תל-אביב" and "תל אביב" behave exactly as before.
# =====================================================================
check("test 4: 'תל-אביב' (hyphen) resolves the same as 'תל אביב' (space)",
      chat._match_city_exact("תל-אביב", AIRPORTS) == chat._match_city_exact("תל אביב", AIRPORTS)
      and chat._match_city_exact("תל אביב", AIRPORTS) == "TLV")

# =====================================================================
# Test 5 (spec): Heraklion/Lyon regression - still never a false match,
# exact-match only, regardless of the new comparison-only normalization.
# =====================================================================
check("test 5 (Heraklion/Lyon regression): 'הרקליון' never matches Lyon's airport",
      chat._match_city_exact("הרקליון", AIRPORTS) != "LYS"
      and chat._match_city_exact("הרקליון", AIRPORTS) == "HER")
check("test 5: 'ליון' (Lyon itself) still correctly resolves to Lyon, not Heraklion",
      chat._match_city_exact("ליון", AIRPORTS) == "LYS")

# =====================================================================
# Test 6 (spec): Saalbach/זאלבאך regression - the resort is still
# recognized (via the existing _DESTINATION_SPELLING_ALIASES entry,
# untouched by this task), not just the country.
# =====================================================================
fact_saalbach = chat._deterministic_destination_facts([], "חופשת סקי בזאלבאך שבאוסטריה")
check("test 6 (Saalbach regression): the specific resort is recognized, "
      "not just the country ('אוסטריה')",
      (fact_saalbach.get("destination") or {}).get("places") == ["זלבאך"])

# =====================================================================
# Test 7 (spec): collision check over the full current catalog - no two
# different real catalog names normalize to the same spelling.
# =====================================================================
_log_capture = StringIO()
_handler = logging.StreamHandler(_log_capture)
_handler.setLevel(logging.WARNING)
logging.getLogger().addHandler(_handler)
chat._KNOWN_DESTINATION_NAMES_CACHE = None
chat._known_destination_names()
logging.getLogger().removeHandler(_handler)
check("test 7: no 020a spelling-collision warning on the current real "
      "catalog - every real catalog name still normalizes to a distinct "
      "spelling",
      "020a" not in _log_capture.getvalue())

# Direct unit coverage of the collision check itself - proves it actually
# fires when a genuine collision exists, not just that it stays silent.
_log_capture2 = StringIO()
_handler2 = logging.StreamHandler(_log_capture2)
_handler2.setLevel(logging.WARNING)
logging.getLogger().addHandler(_handler2)
import unittest.mock as _mock
with _mock.patch.object(chat, "_load_airports", return_value=[
    {"code": "AAA", "city_he": "ולנסיה", "city_en": "Valencia", "country_he": "ספרד", "country_en": "Spain"},
    {"code": "BBB", "city_he": "וולנסיה", "city_en": "Valenciax", "country_he": "ספרד", "country_en": "Spain"},
]):
    chat._KNOWN_DESTINATION_NAMES_CACHE = None
    chat._known_destination_names()
logging.getLogger().removeHandler(_handler2)
check("direct: the collision check DOES fire a warning when two distinct "
      "fabricated catalog names normalize to the same spelling",
      "020a" in _log_capture2.getvalue())
chat._KNOWN_DESTINATION_NAMES_CACHE = None  # restore the real catalog for anything run after this file

# =====================================================================
# Regression (this task's own near-miss, kept as a permanent guard): the
# free-text raw scan must NEVER use fuzzy spelling-variant matching -
# Lyon's doubled-ו variant must not collide with "ל" (to) + "יוון" (Greece).
# =====================================================================
fact_greece = chat._deterministic_destination_facts([], "טסה מחיפה ליוון")
check("regression guard: 'טסה מחיפה ליוון' (flying to Greece) still "
      "resolves to Greece, never Lyon - the free-text scan was "
      "deliberately NOT given fuzzy letter-doubling matching",
      (fact_greece.get("destination") or {}).get("places") == ["יוון"])

# =====================================================================
# Shaked's dry-run 2 finding on #144/#139: _destination_catalog_hint did
# its own plain-casefold comparison, bypassing _match_city_exact entirely -
# so even after the fix above, "וולנסיה" still showed up as "not in our
# catalog" and the redundant "just to confirm - VLC?" question kept
# coming back. Now goes through the same _normalize_he_spelling.
# =====================================================================
hint_valencia = chat._destination_catalog_hint({"destination": {"places": ["וולנסיה"]}})
check("Shaked's dry-run 2 finding: _destination_catalog_hint recognizes "
      "'וולנסיה' as a real catalog city (VLC), not as an unverified "
      "unknown destination",
      "VLC" in hint_valencia and "לא נמצא" not in hint_valencia)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL 020A HEBREW-SPELLING-VARIANT TESTS PASSED")
