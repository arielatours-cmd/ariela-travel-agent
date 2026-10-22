"""QA for Round 12 finding 1 (22.10; Shaked's stage1-live-run12 report, C
Paphos / E Zadar): the model said "no commercial airport" for cities that
have one.

- "פפוס" (no א): per the business owner's decision (22.10, via Shlomo/
  Bezalel) Hebrew spelling variants are left to the model's own knowledge
  (Bezalel's _destination_gateway_answer_by_meaning asks it for city_en +
  IATA and verifies the code against the catalog) - no new aliases.
- Zadar (ZAD) wasn't in our list at all - 020 stage B: Ofek's expanded
  catalog (approved: "the expanded list is enough") ships as
  data/airports_extended.json - the 1,217 airports NOT in
  static/airports.json. Server-side fallback only (the verified catalog
  always wins; static/airports.json / the airport picker are unchanged):
  the catalog hint, the route -> destination_airports resolution and the
  search-time codes. Its Hebrew names are unverified: matching only, the
  English name is what's shown. match_exact_only names are never resolved
  automatically; a name shared by several countries resolves only to its
  preferred_for_names_he default.

Offline. Run: python3 tools/qa_airports_extended_pfo_zad.py
"""
import json
import os
import sys
import time

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


def hint(place):
    return chat._destination_catalog_hint({"destination": {"places": [place]}})


NOT_IN_LIST = "לא נמצא ברשימת"
airports = json.load(open(os.path.join(ROOT, "static", "airports.json"), encoding="utf-8"))
extended = json.load(open(os.path.join(ROOT, "data", "airports_extended.json"), encoding="utf-8"))["airports"]

# --- Data ---------------------------------------------------------------------------------------------------
check("static/airports.json is still the 188 verified airports (the picker is unchanged)", len(airports) == 188)
check("the extended file holds only airports NOT in static/airports.json (1,217)",
      len(extended) == 1217 and not ({a["code"] for a in extended} & {a["code"] for a in airports}))
check("every extended airport is unverified in Hebrew", all(a.get("he_verified") is False for a in extended))
check("no new Hebrew aliases added (the business owner's decision)", not any(a.get("aliases_he") for a in airports if a["code"] in ("PFO", "VLC")))

# --- Paphos: three spellings ---------------------------------------------------------------------------------
for spelling in ("פאפוס", "Paphos"):
    h = hint(spelling)
    check(f"PFO '{spelling}': catalog fact (PFO), never 'not in our list'", "(PFO)" in h and NOT_IN_LIST not in h)
    check(f"PFO '{spelling}': search-time code PFO", public_site._chat_destination_codes([spelling]) == ["PFO"])
    check(f"PFO '{spelling}': _match_city_exact -> PFO", chat._match_city_exact(spelling, chat._load_airports()) == "PFO")

check("the extended catalog's code lookup knows ZAD (what the model's IATA answer is verified against)",
      chat._catalog_airport_by_code("ZAD").get("city_en") == "Zadar" and chat._catalog_airport_by_code("PFO").get("city_en") == "Paphos"
      and chat._catalog_airport_by_code("XXX") is None)

# --- Zadar: three spellings ----------------------------------------------------------------------------------
for spelling in ("זדאר", "זאדאר", "Zadar"):
    h = hint(spelling)
    check(f"ZAD '{spelling}': a real airport fact - never 'no commercial airport'", "Zadar (ZAD), Croatia" in h and NOT_IN_LIST not in h)
    check(f"ZAD '{spelling}': search-time code ZAD", public_site._chat_destination_codes([spelling]) == ["ZAD"])
    check(f"ZAD '{spelling}': the route resolves destination_airports to ZAD",
          chat._resolve_destination_airports_from_route_names(chat._load_airports(), [spelling]) == ["ZAD"])
check("ZAD: the unverified Hebrew name is never shown (English only)", "זאדאר" not in hint("זדאר"))
gw = chat._destination_gateway_summary({"destination": {"places": ["זדאר"]}, "destination_airports": ["ZAD"]})
check("ZAD saved as the landing airport: the summary fact names it (English)", "Zadar (ZAD), Croatia" in gw)

# --- Safety -------------------------------------------------------------------------------------------------
check("the verified catalog always wins: 'ולנסיה' -> VLC (not Venezuela's VLN)",
      public_site._chat_destination_codes(["ולנסיה"]) == ["VLC"] and "(VLC)" in hint("ולנסיה"))
check("a name shared by countries with no default ('ויטוריה') -> not resolved (the model asks)",
      chat._extended_airport_matches("ויטוריה") == [] and public_site._chat_destination_codes(["ויטוריה"]) == [])
check("a shared name WITH a default resolves to it ('ברסט' -> BES, France)",
      [a["code"] for a in chat._extended_airport_matches("ברסט")] == ["BES"])
check("match_exact_only names are never resolved automatically ('קאן' - Caen in the draft, usually Cannes)",
      chat._extended_airport_matches("קאן") == [] and public_site._chat_destination_codes(["קאן"]) == [])
check("a city really missing everywhere (Rovinj) is still flagged", NOT_IN_LIST in hint("רוביני"))
check("an island name stays an island ('כרתים' -> HER+CHQ, never the extended Sitia alias)",
      chat._extended_airport_matches("כרתים") == []
      and set(chat._resolve_destination_airports_from_route_names(chat._load_airports(), ["כרתים"])) == {"HER", "CHQ"})
chat._extended_airport_matches("x")
t = time.time()
for _ in range(200):
    chat._extended_airport_matches("זדאר")
check("lookups are indexed (200 lookups < 0.5s)", time.time() - t < 0.5)

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
