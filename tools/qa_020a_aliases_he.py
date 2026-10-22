"""QA for task 020a (part: catalog spellings - product/dev-tasks/020a-hebrew-
spelling-variants.md on the ofek branch, split with Bezalel 22.10).

static/airports.json carries alternate Hebrew spellings as data:
  - aliases_he         - alternate spellings of the record's city_he
  - country_aliases_he - alternate spellings of the record's country_he
_known_destination_names merges them (a country alias stays in the country
tier), _match_city_exact and public_site._chat_destination_codes accept them,
and the airport-catalog entries left _DESTINATION_SPELLING_ALIASES ("ויאטנם"
moved to the catalog; the ski-resort spellings stay in the map - resorts
aren't in the airport catalog). The customer always sees the official name.

Spec checks covered here: #2 ("ויאטנם" recognized after the move) and the
data side; #8 (qa/run_qa.py unchanged) is run separately. The spelling
normalization itself (#1, #3-#7) is Bezalel's part.

Offline. Run: python3 tools/qa_020a_aliases_he.py
"""
import json
import os
import sys
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("ANTHROPIC_API_KEY", "")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import ariella_chat_clean as chat  # noqa: E402
import public_site  # noqa: E402

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


with open(os.path.join(ROOT, "static", "airports.json"), encoding="utf-8") as fh:
    airports = json.load(fh)

# --- Data ---------------------------------------------------------------------------------------------
bad = [a["code"] for a in airports
       for f in ("aliases_he", "country_aliases_he")
       if f in a and not (isinstance(a[f], list) and all(isinstance(x, str) and x.strip() for x in a[f]))]
check("aliases_he / country_aliases_he are lists of non-empty strings when present", not bad)
vn = [a for a in airports if a.get("country") == "VN"]
check("every Vietnam record carries country_aliases_he ['ויאטנם']", vn and all(a.get("country_aliases_he") == ["ויאטנם"] for a in vn))
official = {str(a.get(k) or "").strip() for a in airports for k in ("city_he", "country_he")}
clash = sorted({x for a in airports for f in ("aliases_he", "country_aliases_he") for x in (a.get(f) or []) if x in official})
check("no alias is itself another place's official name", not clash)
check("_DESTINATION_SPELLING_ALIASES keeps only the ski-resort spellings",
      "ויאטנם" not in chat._DESTINATION_SPELLING_ALIASES and chat._DESTINATION_SPELLING_ALIASES.get("זאלבאך") == "זלבאך")

# --- #2: "ויאטנם" recognized after the move ------------------------------------------------------------
check("#2: 'חופשה חדשה לויאטנם' -> Vietnam, shown by its official name",
      (chat._seed_fresh_trip_from_trigger_message("חופשה חדשה לויאטנם").get("destination") or {}).get("places") == ["וייטנאם"])
check("a country alias stays in the country tier", "ויאטנם" in chat._known_destination_country_needles())
check("search time: a place saved in the alias spelling resolves to Vietnam's airports",
      public_site._chat_destination_codes(["ויאטנם"]) == ["HAN", "SGN", "DAD"])
check("regression #6 (ski spelling, still in the map): Saalbach recognized, not only Austria",
      (chat._seed_fresh_trip_from_trigger_message("חופשת סקי בזאלבאך שבאוסטריה").get("destination") or {}).get("places") == ["זלבאך"])

# --- A city alias, end to end (a new spelling is a data update only) -----------------------------------
patched = [dict(a, aliases_he=["ברסלונה"]) if a.get("code") == "BCN" else a for a in airports]
saved_cache = chat._KNOWN_DESTINATION_NAMES_CACHE
try:
    chat._KNOWN_DESTINATION_NAMES_CACHE = None
    with patch.object(chat, "_load_airports", return_value=patched):
        check("city alias (data only): free text -> the official city name",
              chat._known_destination_names().get("ברסלונה") == "ברצלונה")
        check("city alias: _match_city_exact -> BCN", chat._match_city_exact("ברסלונה", patched) == "BCN")
finally:
    chat._KNOWN_DESTINATION_NAMES_CACHE = saved_cache
with patch.dict(public_site._AIRPORT_LOCALIZATION, {"BCN": dict(public_site._AIRPORT_LOCALIZATION["BCN"], aliases_he=["ברסלונה"])}):
    check("city alias: search time -> BCN only (city tier, not all of Spain)", public_site._chat_destination_codes(["ברסלונה"]) == ["BCN"])
check("without the data entry the spelling isn't known (it really comes from the catalog)",
      chat._known_destination_names().get("ברסלונה") is None)

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
