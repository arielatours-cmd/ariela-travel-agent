"""QA for the fix to Carmit's question ("maybe write airport names in
English/codes to avoid confusion?"). Decided instead: keep Hebrew names,
but Ariella must copy them verbatim from the verified airport catalog
rather than improvising her own transliteration - the actual root cause
behind spelling slips like "חניא ואיראקליון" instead of the catalog's own
"חאניה והרקליון".

_destination_gateway_summary (ariella_chat_clean.py) hands over the
verified Hebrew city name + country for destination_airports and
return_departure_airports as a hard fact block in system_dynamic, mirroring
the existing _departure_summary pattern for the departure airport.

Run: python3 tools/qa_destination_gateway_summary.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

from ariella_chat_clean import _destination_gateway_summary

# --- 1. Open-jaw: landing and return airports differ ---
state = {"destination_airports": ["CHQ"], "return_departure_airports": ["HER"]}
result = _destination_gateway_summary(state)
assert "חאניה (CHQ), יוון" in result, result
assert "הרקליון (HER), יוון" in result, result
print("PASS: open-jaw gateways -> both verified names injected correctly")

# --- 2. Same airport both ways (no explicit return_departure_airports) ---
state2 = {"destination_airports": ["FCO"]}
result2 = _destination_gateway_summary(state2)
assert result2.count("רומא (FCO), איטליה") == 2, result2
print("PASS: single airport (no open-jaw) -> same verified name appears for both landing and return")

# --- 3. Multiple candidate airports, none chosen yet ---
state3 = {"destination_airports": ["LCA", "PFO"]}
result3 = _destination_gateway_summary(state3)
assert "לרנקה (LCA), קפריסין" in result3 and "פאפוס (PFO), קפריסין" in result3, result3
print("PASS: multiple candidate gateways -> both verified names listed")

# --- 4. No destination_airports yet -> no hint injected ---
assert _destination_gateway_summary({}) == ""
print("PASS: no destination_airports -> no hint injected (nothing to verify yet)")

print("\nALL DESTINATION GATEWAY SUMMARY TESTS PASSED")
