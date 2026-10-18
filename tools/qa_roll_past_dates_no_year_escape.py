"""QA for Shlomo's urgent follow-up (18.10.2026, qa/reports/2026-10-18-
stage3-run4.md, s3y2 - Tuscany): a live bug where "1.7 עד 10.7" (no year
stated) was saved as 2026-07-01/2026-07-10 - already in the past, since
today is 2026-10-18 - and the summary showed 2026. A search for flights on
a date that has already passed can never be correct.

_roll_past_dates already existed for exactly this ("day+month without a
year rolls to its next future occurrence"), but its own "did the customer
explicitly type that year" escape scanned the WHOLE conversation text for
the bare digit string of the departure's year - ANY unrelated mention of
that year anywhere (a budget figure, a flight number, anything) would
false-positive and wrongly skip the correction entirely.

Shlomo's explicit instruction (relayed, 18.10): remove that escape
entirely. "גם תאריך מלא שנמצא בעבר לא נשמר" (a full date found to be in
the past is not saved either) - there is no legitimate reason for a
vacation-search bot to keep a departure date in the past, whether the
customer stated the year explicitly or not. _roll_past_dates now always
rolls a past departure forward to its next future occurrence, with no
exception. Its signature was also simplified (message/history dropped -
no longer used by any check inside it).

Run: python3 tools/qa_roll_past_dates_no_year_escape.py
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import ariella_chat_clean as chat

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# =====================================================================
# 1. The original live repro: bare day/month (no year at all) that
#    resolves to a past date rolls forward exactly one year.
# =====================================================================
state1 = {"dates": {"departure": "2026-07-01", "return": "2026-07-10"}}
r1 = chat._roll_past_dates(dict(state1))
check("s3y2 repro: a bare day/month (no year) already in the past rolls forward to next year",
      r1["dates"]["departure"] == "2027-07-01" and r1["dates"]["return"] == "2027-07-10")

# =====================================================================
# 2. The exact false-positive this fix removes: an unrelated mention of
#    the departure's own year digits elsewhere in the conversation must
#    no longer suppress the correction (the escape is gone entirely now).
# =====================================================================
state2 = {"dates": {"departure": "2026-07-01", "return": "2026-07-10"}}
r2 = chat._roll_past_dates(dict(state2))
check("regression fix: with the 'customer typed that year' escape removed, this "
      "still rolls forward regardless of anything the customer wrote elsewhere",
      r2["dates"]["departure"] == "2027-07-01")

# =====================================================================
# 3. Shlomo's explicit instruction: a FULL date (the customer clearly
#    stated the year) that is still in the past is ALSO not saved as-is -
#    it rolls forward too, exactly like the bare-date case. No escape.
# =====================================================================
state3 = {"dates": {"departure": "2026-07-01", "return": "2026-07-10"}}
r3 = chat._roll_past_dates(dict(state3))
check("Shlomo's instruction: a full past date (year included) is never silently "
      "saved as-is either - it rolls forward too, with no exception",
      r3["dates"]["departure"] == "2027-07-01" and r3["dates"]["return"] == "2027-07-10")

# =====================================================================
# 4. Regression: a departure already in the future is left untouched.
# =====================================================================
state4 = {"dates": {"departure": "2027-07-01", "return": "2027-07-10"}}
r4 = chat._roll_past_dates(dict(state4))
check("regression: a departure already in the future is unchanged",
      r4["dates"]["departure"] == "2027-07-01" and r4["dates"]["return"] == "2027-07-10")

# =====================================================================
# 5. Regression: a state with no dates at all, or no departure, is a
#    harmless no-op (never raises).
# =====================================================================
check("regression: a state with no 'dates' key at all is a harmless no-op",
      chat._roll_past_dates({}) == {})
check("regression: dates present but departure missing is a harmless no-op",
      chat._roll_past_dates({"dates": {"return": "2027-07-10"}})["dates"].get("departure") is None)

# =====================================================================
# 6. Multi-year rollover: a departure more than one year in the past
#    (e.g. a stale value from a much earlier conversation) rolls forward
#    to the correct NEXT future year, not just +1 blindly.
# =====================================================================
far_past_year = date.today().year - 3
state6 = {"dates": {"departure": f"{far_past_year}-07-01", "return": f"{far_past_year}-07-10"}}
r6 = chat._roll_past_dates(dict(state6))
rolled_dep = date.fromisoformat(r6["dates"]["departure"])
check("regression: a departure several years in the past rolls forward to the "
      "correct next future year, not a fixed +1",
      rolled_dep >= date.today() and rolled_dep.month == 7 and rolled_dep.day == 1)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL ROLL-PAST-DATES-NO-YEAR-ESCAPE TESTS PASSED")
