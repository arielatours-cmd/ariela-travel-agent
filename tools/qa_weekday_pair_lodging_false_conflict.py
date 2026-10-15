"""QA for a bug Carmit found live on the production site (2026-10-14): after
she had earlier asked Ariella to build a route with "כל 2 ימים לישון באותו
מקום רק בסוף שבוע חמישי עד שבת לישון באותו מקום" (a LODGING instruction -
stay in the same place Thursday-Saturday), she later replied with an exact,
unambiguous date range: "11 לילות 19.9 עד 30.9". Ariella still responded
with a confused "רק לוודא - 19.09.2027 יוצא ביום ראשון, וביקשת חמישי עד
שבת. התכוונת ל-16.09.2027 או 23.09.2027?" - treating her own lodging
grouping instruction from many turns earlier as if it were a weekday-range
constraint on the trip's departure/return days.

Root cause traced directly in _weekday_pair_conflict: it scans ALL of
history backward for literally any "weekday עד weekday" phrase with no
context check at all, so a LODGING instruction containing "חמישי עד שבת"
looked identical to a genuine travel-date request like "ראשון עד חמישי"
(the function's own original, correct use case - see its first docstring
example). Fixed by skipping any historical match whose own message also
talks about lodging/staying in place (לישון/לינה/באותו מקום/...) - that
context is never a travel-date weekday range.

Run: python3 tools/qa_weekday_pair_lodging_false_conflict.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import ariella_chat_clean as chat

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# --- 1. The exact live bug: a lodging-grouping instruction mentioning
#        "חמישי עד שבת" must NOT be mistaken for a trip-date weekday range
#        when the customer later gives an exact, explicit date range ---
lodging_history = [
    {"role": "user", "content": "תבני מסלול. כל 2 ימים לישון באותו מקום רק בסוף שבוע חמישי עד שבת לישון באותו מקום. שבת לא נוסעים אז נוסעים במקום מעניין"},
]
result = chat._weekday_pair_conflict("11 לילות 19.9 עד 30.9", lodging_history)
check("lodging-grouping 'חמישי עד שבת' does not false-trigger a date conflict", result is None)

# --- 2. Variant lodging-context phrasing using "לינה"/"באותו מקום" alone
#        is also excluded ---
lodging_history_2 = [{"role": "user", "content": "אפשר לינה חמישי עד שבת באותו מקום?"}]
check("a '...לינה...' lodging mention with a weekday range is also excluded",
      chat._weekday_pair_conflict("15.8 עד 20.8", lodging_history_2) is None)

# --- 3. The ORIGINAL, genuine use case must keep working: a real travel-
#        date weekday range given with no lodging context at all still
#        catches a real mismatch ---
travel_history = [{"role": "user", "content": "אני רוצה לצאת מראשון עד חמישי"}]
real_conflict = chat._weekday_pair_conflict("28.6", travel_history)
check("a genuine travel-date weekday range still triggers a real conflict",
      real_conflict is not None and "ראשון עד חמישי" in real_conflict)

# --- 4. A genuine travel-date weekday range that already matches the given
#        date correctly returns no conflict (no false positive either way) ---
travel_history_match = [{"role": "user", "content": "יוצאים מיום ראשון עד יום חמישי"}]
check("a correctly-matching date against a real travel weekday range stays silent",
      chat._weekday_pair_conflict("27.6", travel_history_match) is None)

# --- 5. Defensive: no history, or no weekday range anywhere in history,
#        never crashes and returns None ---
check("empty history never crashes", chat._weekday_pair_conflict("19.9 עד 30.9", []) is None)
check("history with no weekday-range mention at all returns None",
      chat._weekday_pair_conflict("19.9 עד 30.9", [{"role": "user", "content": "שלום, רוצה טיול לקרואטיה"}]) is None)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL WEEKDAY-PAIR-LODGING-FALSE-CONFLICT TESTS PASSED")
