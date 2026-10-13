"""QA for the broad airport catalog expansion (2026-10-13, per Carmit:
"אם צריך להגדיל את הטבלה - תגדיל" - grow the table if needed, so a chat
never gets stuck over a missing airport). Adds ~44 commonly-requested
airports across Western Europe, Mediterranean islands, the Middle East,
the Far East and Africa, beyond the 9 added earlier the same day to
unblock Tuscany/Val Thorens specifically.

Run: python3 tools/qa_expanded_airport_catalog.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import ariella_chat_clean as chat

airports = chat._load_airports()
codes = [a["code"] for a in airports]
dupes = {c for c in codes if codes.count(c) > 1}
assert not dupes, f"duplicate airport codes found: {dupes}"
print(f"PASS: no duplicate codes among {len(codes)} total airports")

expected = {
    "MAN": "Manchester", "EDI": "Edinburgh", "HAM": "Hamburg", "CGN": "Cologne",
    "STR": "Stuttgart", "SVQ": "Seville", "BIO": "Bilbao", "VLC": "Valencia",
    "ALC": "Alicante", "TFS": "Tenerife", "LPA": "Gran Canaria", "MAH": "Menorca",
    "BRI": "Bari", "OLB": "Olbia", "GOT": "Gothenburg", "BGO": "Bergen",
    "KEF": "Reykjavik", "DUB": "Dublin", "NTE": "Nantes", "BOD": "Bordeaux",
    "ZTH": "Zakynthos", "SMI": "Samos", "MJT": "Lesvos", "JSI": "Skiathos",
    "KLX": "Kalamata", "SKP": "Skopje", "SJJ": "Sarajevo", "DOH": "Doha",
    "MCT": "Muscat", "PVG": "Shanghai", "CAN": "Guangzhou", "SGN": "Ho Chi Minh City",
    "DAD": "Da Nang", "DPS": "Bali", "CGK": "Jakarta", "MNL": "Manila",
    "KUL": "Kuala Lumpur", "KIX": "Osaka", "RAK": "Marrakech", "CMN": "Casablanca",
    "ZNZ": "Zanzibar", "CPT": "Cape Town", "LAS": "Las Vegas", "MCO": "Orlando",
}
by_code = {a["code"]: a for a in airports}
for code, city_en in expected.items():
    row = by_code.get(code)
    assert row, f"{code} ({city_en}) missing from catalog"
    assert row["city_en"] == city_en, (code, row["city_en"])
    for field in ("city_he", "name_en", "name_he", "country", "country_en", "country_he"):
        assert row.get(field), f"{code} missing/empty field {field}"
print(f"PASS: all {len(expected)} newly added airports present with complete fields")

# Spot-check a representative sample through the real destination-capture
# pipeline (not just the raw catalog) - one per continent/region added.
sample_messages = {
    "רוצה לטוס למנצ'סטר": "מנצ'סטר",
    "טיסה להמבורג": "המבורג",
    "חופשה בבאלי": "באלי",
    "רוצה לנסוע לדוחה": "דוחה",
    "מרקש בבקשה": "מרקש",
    "טיסה ללאס וגאס": "לאס וגאס",
}
for msg, expected_place in sample_messages.items():
    result = chat._deterministic_destination_facts([], msg, {})
    places = result.get("destination", {}).get("places")
    assert places == [expected_place], (msg, places)
print(f"PASS: {len(sample_messages)} sample destinations recognized end-to-end via _deterministic_destination_facts")

print("\nALL EXPANDED AIRPORT CATALOG TESTS PASSED")
