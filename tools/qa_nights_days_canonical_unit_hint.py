"""QA for a critical new product rule the business owner set (15.10.2026),
caused by a live bug she found in the SAME Croatia conversation as the
weekday bug (screenshot: ceo/evidence/2026-10-15-croatia-nights-days.jpg):

Ariella had already built a correct 12-day route for an 11-night trip
(19.9 departure, 30.9 return - verified: (30-19)=11 nights=12 days). After
day 12, she wrote: "רגע, שמתי לב שיצא לי 12 יום במקום 11 לילות בדיוק.
בואי אתקן: אאחד את ימי 3-4..." and started merging/deleting a real day of
an already-correct route - because 11 nights and 12 days are the SAME
trip length (nights = days - 1, always), but nothing ever told her that
explicitly, so two correct numbers looked like a contradiction.

Her product rule: one canonical unit (days, chosen here - route headers
already say "יום N" throughout the whole system), the other unit is
translated ONCE from whatever the customer says (already handled
correctly by _deterministic_duration_facts - unaffected by this change),
computed in CODE from departure/return dates (not guessed by the model),
and Ariella never "corrects" a route that already matches the right count.

Fixed by strengthening _total_nights_hint (already an existing, proven
"hand over the exact pre-computed fact" hint) to state both numbers
together with the day=nights+1 identity spelled out explicitly, instruct
route headers to speak in days, and forbid treating an already-matching
route as something to fix.

Run: python3 tools/qa_nights_days_canonical_unit_hint.py
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


# --- 1. The exact live scenario: 19.9 -> 30.9 is 11 nights / 12 days ---
state = {"dates": {"departure": "2027-09-19", "return": "2027-09-30", "needs_confirmation": False}}
hint = chat._total_nights_hint(state)
check("states the correct day count (12)", "12 ימים" in hint)
check("states the correct night count (11)", "11 לילות" in hint)
check("explicitly spells out the days=nights+1 identity (not two separate facts)",
      "אותו אורך טיול" in hint)
check("instructs route headers to speak in days specifically",
      "בכותרות המסלול" in hint and "דברי תמיד במונח הימים" in hint)
check("explicitly forbids 'fixing' an already-matching route",
      "אל 'תתקני' אותו" in hint)
check("tells her how a REAL mismatch is actually detected (counting 'יום N' headers, not comparing to nights)",
      "סופרים את כותרות" in hint)

# --- 2. Regression guard: a single-night trip (edge case: days=nights+1
#        still holds, 1 night = 2 days) ---
state_short = {"dates": {"departure": "2027-09-19", "return": "2027-09-20", "needs_confirmation": False}}
hint_short = chat._total_nights_hint(state_short)
check("a 1-night trip correctly states 2 days / 1 night",
      "2 ימים" in hint_short and "1 לילות" in hint_short)

# --- 3. Regression guard: _deterministic_duration_facts is untouched -
#        "11 לילות" stated by the customer still correctly becomes 12 days ---
dep_only_state = {"dates": {"departure": "2027-09-19"}}
result = chat._deterministic_duration_facts("11 לילות בבקשה", dep_only_state)
check("customer stating '11 לילות' still correctly computes duration_days=12",
      result.get("dates", {}).get("duration_days") == 12)
result_days = chat._deterministic_duration_facts("12 ימים בבקשה", {"dates": {"departure": "2027-09-19"}})
check("customer stating '12 ימים' directly still correctly computes duration_days=12",
      result_days.get("dates", {}).get("duration_days") == 12)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL NIGHTS-DAYS-CANONICAL-UNIT-HINT TESTS PASSED")
