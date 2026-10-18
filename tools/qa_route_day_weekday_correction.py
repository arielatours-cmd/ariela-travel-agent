"""QA for a bug Carmit found live on the production site (2026-10-14): in a
Croatia-planning conversation where Ariella had already correctly confirmed
"יציאה ביום ראשון... יוצא טיסה ב-20.9.2026 (ראשון)", the day-by-day route she
built right afterwards opened with "יום 1, 20.9 (שני)" for that exact same
date - a real-weekday mismatch within the same conversation, even though
_weekday_lookup_hint hands her a precomputed, verified weekday table on
every single turn (confirmed correct: date(2026,9,20).weekday() -> Sunday ->
"ראשון").

Rather than rely on prompt-following alone for a customer-facing fact,
_correct_route_day_weekdays deterministically recomputes the real weekday for
every "יום N, D.M(.YYYY)? (weekday)" row in the final reply text and fixes any
mismatch outright - the same "hand over arithmetic, don't trust the model to
compute it" pattern already used for _weekday_lookup_hint/_total_nights_hint
themselves, just applied as a final safety net on the actual output.

Also covers Carmit's explicit year-rollover instruction ("אם התאריך הוא בחודש
שכבר עבר השנה אז הכוונה היא לשנה העוקבת"): when a day row omits the year (as
it does after day 1 in real itineraries), the year is inferred from the
confirmed trip departure date, rolling over to next year for a
December-into-January route.

Run: python3 tools/qa_route_day_weekday_correction.py
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


# --- 1. The exact live bug: day 1 IS the departure date itself, already
#        confirmed elsewhere in the conversation as ראשון (Sunday) - the
#        route text wrongly says שני (Monday) -> must be corrected ---
state = {"dates": {"departure": "2026-09-20", "return": "2026-09-28"}}
buggy = "יום 1, 20.9 (שני) - נחיתה בזאגרב, התבססות בעיר. לינה בזאגרב."
fixed = chat._correct_route_day_weekdays(buggy, state)
check("day-1 mismatch (שני -> ראשון) is corrected", "יום 1, 20.9 (ראשון)" in fixed)
check("the wrong weekday word no longer appears for that row", "20.9 (שני)" not in fixed)

# --- 2. A correct weekday in the model's own text is left untouched (never
#        rewritten when it already matches) ---
already_correct = "יום 1, 20.9 (ראשון) - נחיתה בזאגרב."
check("already-correct weekday is left byte-for-byte untouched",
      chat._correct_route_day_weekdays(already_correct, state) == already_correct)

# --- 3. Multi-day route, year omitted after day 1, spans a week - every
#        row corrected independently and consistently with the real
#        calendar, regardless of what the model guessed ---
multi = (
    "יום 1, 20.9 (שני) - זאגרב.\n"
    "יום 2, 21.9 (רביעי) - זאגרב.\n"
    "יום 3, 22.9 (שישי) - פלא.\n"
)
fixed_multi = chat._correct_route_day_weekdays(multi, state)
check("multi-day route: day 1 (20.9) corrected to ראשון", "יום 1, 20.9 (ראשון)" in fixed_multi)
check("multi-day route: day 2 (21.9) corrected to שני", "יום 2, 21.9 (שני)" in fixed_multi)
check("multi-day route: day 3 (22.9) corrected to שלישי", "יום 3, 22.9 (שלישי)" in fixed_multi)

# --- 4. Year-rollover: a December->January route with the year omitted
#        must infer the NEXT year once the month/day has rolled past the
#        departure's own year, per Carmit's explicit instruction ---
state_rollover = {"dates": {"departure": "2026-12-28", "return": "2027-01-05"}}
rollover_text = "יום 1, 28.12 (שני) - הגעה.\nיום 5, 1.1 (שישי) - סיור."
import datetime
real_dec28 = chat._WEEKDAY_HE_BY_PY[datetime.date(2026, 12, 28).weekday()]
real_jan1 = chat._WEEKDAY_HE_BY_PY[datetime.date(2027, 1, 1).weekday()]
fixed_rollover = chat._correct_route_day_weekdays(rollover_text, state_rollover)
check("Dec day (same year as departure) gets the real weekday",
      f"יום 1, 28.12 ({real_dec28})" in fixed_rollover)
check("Jan day with omitted year rolls over to the departure's NEXT year",
      f"יום 5, 1.1 ({real_jan1})" in fixed_rollover)

# --- 5. Explicit 4-digit year in the text is trusted and used as-is,
#        never overridden by the departure-date anchor ---
explicit_year = "יום 1, 20.9.2026 (שני)"
fixed_explicit = chat._correct_route_day_weekdays(explicit_year, state)
check("explicit year in text is corrected using that exact year",
      "יום 1, 20.9.2026 (ראשון)" in fixed_explicit)

# --- 6. No departure date known at all, and no explicit year in the text
#        -> cannot safely infer a year, so the row is left untouched rather
#        than guessed ---
no_anchor_text = "יום 1, 20.9 (שני) - נחיתה."
check("no departure date in state and no explicit year -> left untouched (never guessed)",
      chat._correct_route_day_weekdays(no_anchor_text, {}) == no_anchor_text)

# --- 7. Defensive: text with no day-route rows at all, or malformed state,
#        never crashes and returns the text unchanged ---
check("plain text with no route rows passes through unchanged",
      chat._correct_route_day_weekdays("שלום, איך אפשר לעזור?", state) == "שלום, איך אפשר לעזור?")
check("None text never crashes", chat._correct_route_day_weekdays(None, state) == "")
check("non-dict state never crashes", chat._correct_route_day_weekdays(buggy, None) is not None)

# --- 8. Invalid calendar date inside a row (e.g. 31.4, April has no 31st)
#        never crashes - that row is just left as-is ---
invalid_date = "יום 1, 31.4 (שני) - משהו."
check("invalid calendar date (31.4) never crashes, row left untouched",
      chat._correct_route_day_weekdays(invalid_date, state) == invalid_date)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL ROUTE-DAY-WEEKDAY-CORRECTION TESTS PASSED")
