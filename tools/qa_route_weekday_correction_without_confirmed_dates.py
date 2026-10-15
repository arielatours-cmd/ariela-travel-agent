"""QA for a critical live bug the business owner found herself (15.10.2026)
on a Split -> Dubrovnik route: day 10 (28.9) was labeled "רביעי" (Wednesday)
and day 11 (29.9) "חמישי" (Thursday), while day 9 (27.9) was correctly
"שני" (Monday) - Tuesday got silently skipped and every later day shifted
one weekday forward. Verbatim text (from ceo/evidence/2026-10-15-croatia-
weekday-bug.jpg, relayed by Shlomo):

  "יום 9, 27.9 (שני) - נסיעה לאזור דוברובניק..."
  "יום 10, 28.9 (רביעי) - יום ים..."
  "יום 11, 29.9 (חמישי) - תחילת סוף השבוע השני..."

_correct_route_day_weekdays already exists and already recomputes every
"D.M (weekday)" occurrence deterministically - but it only ever had an
anchor date to infer the (omitted) year from state["dates"]["departure"].
A route is often built BEFORE flight dates are confirmed (per product
design - "you can ask me to build the route first, and we'll derive the
gateway/dates from it"), so `anchor` was None, and the whole function
silently passed every weekday through unchecked - day 9 was only right by
the model's own luck; days 10-11 were its own wrong guesses.

Fixed with two fallback tiers when no confirmed departure date exists:
1. The route's own first explicitly-year-bearing date in the text (route
   day 1 almost always has one, e.g. "20.9.2026").
2. date.today() as the last resort (with the same next-year rollover
   logic already used for a real anchor).

Run: python3 tools/qa_route_weekday_correction_without_confirmed_dates.py
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import ariella_chat_clean as chat

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# --- 1. The exact live bug, verbatim, with dates never confirmed at all ---
LIVE_TEXT = (
    "לינה בספליט.\n\n"
    "יום 9, 27.9 (שני) - נסיעה לאזור דוברובניק, עם עצירה בדרך בעיירה החופית סטון (Ston) "
    "הידועה בחומותיה ובצדפות. לינה בדוברובניק (לילה 1 מתוך 2).\n\n"
    "יום 10, 28.9 (רביעי) - יום ים - חוף Banje או שיט קצר לאי לוקרום (Lokrum), "
    "עם נוף ומים נעימים. לינה בדוברובניק (לילה 2).\n\n"
    "יום 11, 29.9 (חמישי) - תחילת סוף השבוע השני: הליכה על החומות העתיקות של דוברובניק "
    "בבוקר הקריר, ואחר הצהריים זמן חופשי בעיר. לינה בדוברובניק (לילה שלישי)."
)
fixed = chat._correct_route_day_weekdays(LIVE_TEXT, {"dates": {}})
check("day 9 (27.9) stays שני (was already correct)", "27.9 (שני)" in fixed)
check("day 10 (28.9) is corrected to שלישי, never left as the wrong רביעי",
      "28.9 (שלישי)" in fixed and "28.9 (רביעי)" not in fixed)
check("day 11 (29.9) is corrected to רביעי, never left as the wrong חמישי",
      "29.9 (רביעי)" in fixed and "29.9 (חמישי)" not in fixed)

# --- 2. Same text, state["dates"] missing entirely (not just empty) ---
fixed_no_dates_key = chat._correct_route_day_weekdays(LIVE_TEXT, {})
check("still corrects with no 'dates' key in state at all",
      "28.9 (שלישי)" in fixed_no_dates_key and "29.9 (רביעי)" in fixed_no_dates_key)

# --- 3. When the route's own day 1 carries an explicit year, that year is
#        used as the anchor instead of today - so a route for a date range
#        far from today still resolves correctly ---
text_with_year = (
    "יום 1, 20.9.2026 (ראשון) - הגעה.\n\n"
    "יום 2, 21.9 (שני) - יום חופשי.\n\n"
    "יום 3, 23.9 (חמישי) - המשך הטיול."
)
fixed_with_year = chat._correct_route_day_weekdays(text_with_year, {"dates": {}})
check("day 1's own explicit year (2026) anchors the rest of the route",
      "21.9 (שני)" in fixed_with_year)
check("day 3 corrects from the wrong 23.9 (חמישי) using that same anchor year",
      "23.9 (רביעי)" in fixed_with_year)

# --- 4. Regression guard: a real confirmed departure date still wins over
#        both fallback tiers (the original, already-tested behavior) ---
real_date = date.today() + timedelta(days=200)
wrong_weekday = chat._WEEKDAY_HE_BY_PY[(real_date.weekday() + 1) % 7]
text_confirmed = f"יום 1, {real_date.day}.{real_date.month} ({wrong_weekday}) - הגעה."
fixed_confirmed = chat._correct_route_day_weekdays(text_confirmed, {"dates": {"departure": real_date.isoformat()}})
correct_weekday = chat._WEEKDAY_HE_BY_PY[real_date.weekday()]
check("a real confirmed departure date still overrides a wrong weekday as before",
      f"({correct_weekday})" in fixed_confirmed)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL ROUTE-WEEKDAY-CORRECTION-WITHOUT-CONFIRMED-DATES TESTS PASSED")
