"""QA for run-10 #3 (Toruń, 22.10): "נחיתה: טורון, קרואטיה" - Toruń is in
Poland and has no commercial airport.

Findings:
  - destination_airports is set in state only for route/ski/gateway-narrow
    cases; a plain city trip gets its codes at SEARCH time (public_site.
    _chat_destination_codes, exact catalog match), so it is normally absent
    from trip_update - by design, not lost.
  - with nothing in state, _destination_gateway_summary gave the model no
    fact at all, and the summary's "נחיתה:" line came from its memory.
  - a city missing from our catalog (Genoa) still searches correctly only
    because public_site._chat_recover_search_facts recovers the IATA code
    the model wrote - so the fix must NOT forbid naming a code.

Fix (a hint BEFORE the reply, no after-the-fact text filtering):
_destination_catalog_hint gives the catalog airport for a known city as a
source-of-truth fact, and for a city not in the catalog an explicit
accuracy instruction (real airport, real code, the country the city is
really in; no airport -> say so and offer the nearest). Countries: no hint.

Offline. Run: python3 tools/qa_destination_catalog_hint.py
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


import ariella_chat_clean as chat  # noqa: E402

summ = chat._destination_gateway_summary


def s(places, **extra):
    return summ({"destination": {"places": places}, **extra})


# --- Toruń: not in the catalog -> accuracy instruction, no invented fact ---------------
t = s(["טורון"])
check("Toruń: told it's not in our airport list (no verified fact)", "לא נמצא ברשימת שדות התעופה שלנו" in t)
check("Toruń: must be a real airport, real code, in the city's real country",
      "שדה תעופה מסחרי אמיתי" in t and "הקוד הנכון" in t and "במדינה שבה העיר באמת נמצאת" in t)
check("Toruń: no airport -> say so and offer the nearest, in one question", "השדה הקרוב ביותר בשאלה אחת" in t)
check("Toruń: the hint itself never names a country or code", "קרואטיה" not in t and "פולין" not in t and "(" not in t.split("שדות התעופה שלנו")[0])
check("Toruń: the summary's 'נחיתה:' line is covered explicitly", 'בשורת "נחיתה:" בסיכום' in t)
check("not a ban on naming a code (search recovery for Genoa-like cities still works)", "אסור לכתוב" not in t)

# --- A catalog city -> the airport as a fact -----------------------------------------------------
split = s(["ספליט"])
check("Split (in the catalog) -> 'ספליט (SPU), קרואטיה' as the landing fact", "ספליט (SPU), קרואטיה" in split and "מקור אמת" in split)
check("English city name matches too", "SPU" in s(["Split"]))
check("a catalog city gets no 'not in our list' instruction", "לא נמצא ברשימת" not in split)

# --- Unchanged ------------------------------------------------------------------------------------
check("a country (פולין) -> no hint (nothing guessed for a whole country)", s(["פולין"]) == "")
check("no destination -> no hint", summ({}) == "" and s([]) == "")
with_codes = summ({"destination": {"places": ["טורון"]}, "destination_airports": ["KRK"]})
check("destination_airports set -> the existing gateway fact wins (unchanged)",
      "קרקוב (KRK), פולין" in with_codes and "לא נמצא ברשימת" not in with_codes)

# --- It reaches the model before the reply ------------------------------------------------------------
captured = {}


def fake(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    captured[source] = system_dynamic
    return "בסדר."


with patch.object(chat, "_post_claude", side_effect=fake):
    chat._call_tinkerbell("k", "m", [], "לטורון", {"destination": {"places": ["טורון"]}})
check("the hint is in Tinkerbell's system_dynamic", "לא נמצא ברשימת שדות התעופה שלנו" in (captured.get("tinkerbell_reply") or ""))

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
