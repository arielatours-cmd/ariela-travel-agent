"""QA for Shlomo's relay of Shaked's live stage-1 run-1 finding (20.10.2026,
b71506d, 1/5 - qa/reports/2026-10-20-stage1-live-run1.md on the shaked
branch), priority fix #4 of four blocking stage-1 - the relative-dates part
Shlomo said comes before everything else ("שלמה אומר שזה קודם לכל השאר"):

s1a5 (קרקוב): "לקרקוב בסוף החודש הבא, שבוע".
אריאלה שאלה "רק לוודא - סוף נובמבר 2026?", הלקוחה ענתה "כן, סוף נובמבר".
נשמר רק dates={period:'סוף נובמבר 2026', duration_days:7, departure:None,
return:None} - ariella_start_flight_search מחשב month רק כש-period מתחיל
בספרות, ולכן החיפוש נכשל ב"חסרים תאריכי חיפוש".

Two compounding gaps in _deterministic_period_facts, on top of the
weekday-pair fix already in this same PR:

1. "בסוף החודש הבא" names no literal month at all - it's itself a relative
   reference ("next month"). The function required an actual month NAME
   (one of the 12 Hebrew names) to even start; with none in the customer's
   own message, it silently returned {} - leaving Tinkerbell to freely
   invent her own period-only proposal ("רק לוודא - סוף נובמבר 2026?")
   with no real candidate dates behind it, never saving concrete
   departure/return even after being confirmed.
2. The function ALSO required a weekday pair ("ראשון עד חמישי") to ever
   produce candidates at all - "סוף החודש הבא, שבוע" names a part-of-month
   and a plain duration, but no weekday pair whatsoever, so even a message
   that did name an actual month would still have returned {} here.

Both fixed: find_month now also resolves "החודש הבא" and "החודש (הזה/
הנוכחי)" directly against today's date, and a new branch handles a
part-of-month + stated duration with NO weekday pair, offering two
concrete departure/return candidates (each showing its own naturally-
occurring day of week, never invented) spread across the requested window
- the same "propose exact dates, ask for confirmation once" pattern as
the weekday-pair case, just without a weekday to anchor on.

Run: python3 tools/qa_relative_month_duration_no_weekday.py
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


# =====================================================================
# Shaked's exact s1a5 message, in one go: "לקרקוב בסוף החודש הבא, שבוע"
# names no literal month AND no weekday pair - both gaps must be closed
# together for this to resolve at all.
# =====================================================================
r = chat._deterministic_period_facts("לקרקוב בסוף החודש הבא, שבוע", [])
check("s1a5's exact message resolves to real candidate_ranges (not {})",
      bool(r.get("dates", {}).get("candidate_ranges")))
check("needs_confirmation=True - a genuine confirmation is still required, "
      "never a silent guess",
      r.get("dates", {}).get("needs_confirmation") is True)
check("departure/return stay None until the customer actually picks a "
      "candidate",
      r["dates"]["departure"] is None and r["dates"]["return"] is None)
check("every candidate shows its own real day of week next to the exact "
      "date (invented from the actual calendar date, not a guess)",
      all("יום " in c for c in r["dates"]["candidate_ranges"]))

# =====================================================================
# "החודש הבא" (next month) resolves correctly regardless of how the
# customer answers afterward - not only when they happen to repeat the
# literal month name back (as in the real transcript's "כן, סוף נובמבר").
# =====================================================================
r_bare = chat._deterministic_period_facts("רוצים לטוס בתחילת החודש הבא, שבועיים", [])
check("'החודש הבא' + a different duration ('שבועיים') also resolves on "
      "its own, without needing the customer to repeat a literal month "
      "name back",
      bool(r_bare.get("dates", {}).get("candidate_ranges")))

# =====================================================================
# "החודש"/"החודש הזה" (this month) also resolves, against today's date.
# =====================================================================
r_this_month = chat._deterministic_period_facts("רוצים לטוס בסוף החודש, שבוע", [])
check("'סוף החודש' (this month, no 'הבא') resolves too",
      bool(r_this_month.get("dates", {}).get("candidate_ranges")))

# =====================================================================
# Regression: a genuine weekday-pair message (from this PR's earlier fix)
# still takes priority and produces its own weekday-named candidates -
# this new branch must never fire when a real pair IS present.
# =====================================================================
r_pair = chat._deterministic_period_facts("רוצים לטוס בסוף יוני, ראשון עד חמישי", [])
check("regression: a message WITH a genuine weekday pair still uses the "
      "customer's own named weekdays (ראשון/חמישי), not this new "
      "no-weekday branch",
      all("יום ראשון" in c and "יום חמישי" in c for c in r_pair["dates"]["candidate_ranges"]))

# =====================================================================
# Regression: a part-of-month with NO duration stated at all must still
# return {} - there is nothing concrete to compute without either a
# weekday pair or a stated duration.
# =====================================================================
check("regression: a part-of-month mention with no duration and no "
      "weekday pair at all still returns {} - nothing concrete to offer",
      chat._deterministic_period_facts("רוצים לטוס בסוף נובמבר", []) == {})

# =====================================================================
# A candidate from this new branch is still accepted correctly by the
# existing candidate-choice mechanisms (ordinal / exact substring).
# =====================================================================
_state_with_candidates = {"dates": {
    "departure": None, "return": None, "needs_confirmation": True,
    "candidate_ranges": r["dates"]["candidate_ranges"],
}}
chosen = chat._deterministic_candidate_choice_facts("הראשון מתאים", _state_with_candidates)
check("choosing 'הראשון' against this new branch's candidates resolves to "
      "exact ISO dates with needs_confirmation=False",
      bool(chosen.get("dates", {}).get("departure")) and chosen["dates"]["needs_confirmation"] is False)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL RELATIVE-MONTH-DURATION-NO-WEEKDAY TESTS PASSED")
