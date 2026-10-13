"""QA for Shaked's bugs 2+3 (2026-10-12, second live round): Ariella
computed a date's day-of-week herself twice and got it wrong - once
shifting an entire Montenegro route by two days, once reading a Barcelona
route's own day-N numbering ("יום ראשון/שני/שלישי...") as real weekdays,
duplicating "שישי" on day 7. _weekday_lookup_hint (ariella_chat_clean.py)
now hands the model an exact, pre-computed date->weekday table instead of
letting it compute one. Uses substring checks (not cases.json's exact-
match "expect"), since the real return value is a full sentence the table
is embedded in.

Run: python3 tools/qa_weekday_lookup_hint.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

from ariella_chat_clean import _weekday_lookup_hint

# --- 1. Montenegro: 20.6.2027 is really a Sunday (Shaked's report: Ariella said Friday) ---
hint = _weekday_lookup_hint({"dates": {"departure": "2027-06-20", "return": "2027-06-27", "needs_confirmation": False}})
assert "20.06.2027=ראשון" in hint, hint
assert "27.06.2027=ראשון" in hint, hint
print("PASS: Montenegro trip (20.6-27.6.2027) table correctly starts and ends on Sunday")

# --- 2. Barcelona: 3.3.2027 is really a Wednesday (Shaked's report: labeled as if Sunday) ---
hint2 = _weekday_lookup_hint({"dates": {"departure": "2027-03-03", "return": "2027-03-09", "needs_confirmation": False}})
assert "03.03.2027=רביעי" in hint2, hint2
assert "09.03.2027=שלישי" in hint2, hint2
print("PASS: Barcelona trip (3.3-9.3.2027) table correctly starts Wednesday, ends Tuesday")

# --- 3. No dates known -> empty (nothing to inject yet) ---
assert _weekday_lookup_hint({}) == ""
assert _weekday_lookup_hint({"dates": {}}) == ""
print("PASS: no confirmed dates -> no hint injected")

# --- 4. Dates still pending confirmation (candidate ranges, not settled) -> empty ---
assert _weekday_lookup_hint({"dates": {"departure": "2027-03-03", "return": "2027-03-09", "needs_confirmation": True}}) == ""
print("PASS: needs_confirmation=true -> no hint injected yet (dates aren't settled)")

# --- 5. An unusually long trip (>31 days) is skipped to avoid prompt bloat ---
assert _weekday_lookup_hint({"dates": {"departure": "2027-01-01", "return": "2027-03-01", "needs_confirmation": False}}) == ""
print("PASS: a 59-day span is skipped (capped at 31 days)")

# --- 6. The table covers every single day in the range, not just the endpoints ---
hint3 = _weekday_lookup_hint({"dates": {"departure": "2027-03-03", "return": "2027-03-09", "needs_confirmation": False}})
for day, expected in [("03.03.2027", "רביעי"), ("04.03.2027", "חמישי"), ("05.03.2027", "שישי"),
                       ("06.03.2027", "שבת"), ("07.03.2027", "ראשון"), ("08.03.2027", "שני"), ("09.03.2027", "שלישי")]:
    assert f"{day}={expected}" in hint3, (day, expected, hint3)
print("PASS: every day in the range appears in the table with its correct weekday")

print("\nALL WEEKDAY LOOKUP HINT TESTS PASSED")
