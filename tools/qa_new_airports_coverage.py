"""QA for the 9 airports added to static/airports.json per Carmit's decision
(2026-10-13): every airport a customer requests must work - missing ones get
added from reliable IATA data, never invented by the model.

FLR/PSA (Florence/Pisa - unblocks the Tuscany scenario), LIN (Milan Linate),
CIA (Rome Ciampino), BSL (Basel), PMI (Palma de Mallorca), FAO (Faro),
CMF/GNB (Chambery/Grenoble - the Val Thorens ski gateways Shaked named).

Run: python3 tools/qa_new_airports_coverage.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import config
import ariella_chat_clean as chat

airports = {a["code"]: a for a in chat._load_airports()}
expected = {
    "FLR": ("Florence", "פירנצה", "Italy"),
    "PSA": ("Pisa", "פיזה", "Italy"),
    "LIN": ("Milan", "מילאנו", "Italy"),
    "CIA": ("Rome", "רומא", "Italy"),
    "BSL": ("Basel", "באזל", "Switzerland"),
    "PMI": ("Palma de Mallorca", "פלמה דה מיורקה", "Spain"),
    "FAO": ("Faro", "פארו", "Portugal"),
    "CMF": ("Chambery", "שמברי", "France"),
    "GNB": ("Grenoble", "גרנובל", "France"),
}
for code, (city_en, city_he, country_en) in expected.items():
    row = airports.get(code)
    assert row, f"{code} missing from _load_airports()"
    assert row["city_en"] == city_en, (code, row["city_en"])
    assert row["city_he"] == city_he, (code, row["city_he"])
    assert row["country_en"] == country_en, (code, row["country_en"])
print(f"PASS: all {len(expected)} new airports present with correct city/country")

# The actual bug this unblocks: Florence must now be a known destination.
tuscany_msg = (
    "חופשה רגילה. כבר הזמנו טיסות לפירנצה: נוחתים ב-5/9/2027 ב-10:00 "
    "וחוזרים ב-12/9/2027 ב-18:00, אני ובעלי. צריכה רק תכנון מסלול בטוסקנה ולינה. בלי רכב"
)
result = chat._deterministic_destination_facts([], tuscany_msg, {})
assert result.get("destination", {}).get("places") == ["פירנצה"], result
print("PASS: Tuscany scenario - 'פירנצה' now recognized as destination.places")

# Milan/Rome must still group correctly as multi-gateway cities (LIN joins MXP,
# CIA joins FCO) rather than silently creating a second, disconnected entry.
assert "לונדון" in config.MULTI_GATEWAY_CITIES  # sanity: existing grouping unaffected
milan_group = config.MULTI_GATEWAY_CITIES.get("מילאנו") or []
rome_group = config.MULTI_GATEWAY_CITIES.get("רומא") or []
milan_codes = {o["code"] for o in milan_group}
rome_codes = {o["code"] for o in rome_group}
# BGY's own city_en is "Bergamo" (a separate city in the catalog, even
# though its name_en is "Milan Bergamo Airport"), so it was never part of
# this grouping - only MXP/LIN share city_en="Milan".
assert {"MXP", "LIN"} <= milan_codes, milan_codes
assert {"FCO", "CIA"} <= rome_codes, rome_codes
print("PASS: Milan (MXP/LIN) and Rome (FCO/CIA) group together as multi-gateway cities")

print("\nALL NEW AIRPORT COVERAGE TESTS PASSED")
