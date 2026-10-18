"""QA for a live bug Shaked found (qa-s92, a ski trip with one child):
every lodging search with children>0 came back "החיפוש נכשל" (the search
failed). Per SerpApi's own google_hotels API reference, children_ages must
list exactly as many ages as the children count whenever children>0 - a
mismatch (here: children=1, no children_ages sent at all) is a parameter
error the API rejects outright, not just an ignored hint.

scanner.search_hotels never accepted or sent children_ages at all. Fixed:
it now takes an optional children_ages list and sends it as SerpApi's
comma-separated children_ages param, but ONLY when the count of valid ages
exactly matches children - never guessing a missing age, and never sending
a mismatched list that would cause the exact same rejection. public_site.
_run_lodging_search now sources this from answers["age_groups"] (the same
field flight search already uses for child ages) and passes it through
both call sites (the single-search and per-location-segment paths).

Run: python3 tools/qa_lodging_children_ages_param.py
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import config
config.SERPAPI_API_KEY = "qa-fake-key"

import scanner

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


captured = {}


def fake_serpapi_request(params):
    captured.clear()
    captured.update(params)
    return {"properties": []}


# --- 1. The exact live scenario: one child, one matching age - the
#        request must now include children_ages ---
with patch.object(scanner, "_serpapi_request", side_effect=fake_serpapi_request):
    scanner.search_hotels("Bansko", "2027-01-10", "2027-01-15", adults=2, children=1, children_ages=[8])
check("children=1 with a matching age sends children_ages='8'",
      captured.get("children_ages") == "8")
check("children count itself is still sent as before",
      captured.get("children") == "1")

# --- 2. Multiple children, multiple matching ages - comma-separated ---
with patch.object(scanner, "_serpapi_request", side_effect=fake_serpapi_request):
    scanner.search_hotels("Bansko", "2027-01-10", "2027-01-15", adults=2, children=2, children_ages=[8, 11])
check("children=2 with two matching ages sends 'children_ages=8,11'",
      captured.get("children_ages") == "8,11")

# --- 3. No children at all - children_ages must never be sent, same as
#        before (no behavior change for the common no-children case) ---
with patch.object(scanner, "_serpapi_request", side_effect=fake_serpapi_request):
    scanner.search_hotels("Sofia", "2027-01-10", "2027-01-15", adults=2, children=0, children_ages=[])
check("children=0 never sends children_ages", "children_ages" not in captured)

# --- 4. children>0 but NO ages supplied at all (the exact live bug's
#        starting state, before this fix's call sites were updated) -
#        never send a mismatched/empty children_ages rather than guess ---
with patch.object(scanner, "_serpapi_request", side_effect=fake_serpapi_request):
    scanner.search_hotels("Bansko", "2027-01-10", "2027-01-15", adults=2, children=1, children_ages=None)
check("children=1 with no ages available never sends a bogus children_ages",
      "children_ages" not in captured)
check("children count is still sent even without ages (unchanged request shape otherwise)",
      captured.get("children") == "1")

# --- 5. A mismatched count (fewer ages than children) is never sent either
#        - sending a short list would be the same kind of mismatch error ---
with patch.object(scanner, "_serpapi_request", side_effect=fake_serpapi_request):
    scanner.search_hotels("Bansko", "2027-01-10", "2027-01-15", adults=2, children=2, children_ages=[8])
check("a mismatched ages count (1 age for 2 children) is never sent",
      "children_ages" not in captured)

# --- 6. Ages are clamped into SerpApi's documented 1-17 range (a child
#        under 1 is treated as age 1 per their own docs) ---
with patch.object(scanner, "_serpapi_request", side_effect=fake_serpapi_request):
    scanner.search_hotels("Bansko", "2027-01-10", "2027-01-15", adults=2, children=1, children_ages=[0])
check("an age of 0 is clamped up to 1 (SerpApi's documented floor)",
      captured.get("children_ages") == "1")

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL LODGING-CHILDREN-AGES-PARAM TESTS PASSED")
