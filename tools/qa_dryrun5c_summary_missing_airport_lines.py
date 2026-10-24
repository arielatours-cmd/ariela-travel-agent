"""QA for dry-run 5c item 4 (Shlomo/Shaked, 22.10.2026, qa/reports/
2026-10-22-dryrun5c.md, scenario D, Hamburg): after confirming a pending
date-shift candidate ("כן"), the reply came back as:

"מצוין, הטיסה עכשיו

תקציב לאדם: 1200 שקלים
כבודה: טרולי 8-10 ק"ג לכל נוסע (בהתאם לתנאי חברת התעופה)
תאריכים: 07.05.2027 - 11.05.2027
נוסעים: 2 מבוגרים
העדפת טיסה: אין העדפה לטיסה ישירה
אם כל שאר הפרטים נכונים, כתבי מאשרת."

- budget/baggage/dates/travelers/connection-preference were all present
(correctly protected by the existing _ensure_flight_summary_completeness
checks), but "יציאה:"/"נחיתה:"/"המראה בחזרה:" (departure/landing/return-
departure) were missing entirely, even though TINKERBELL_SYSTEM's own
summary rule says these lines may never be omitted - this safety net
simply never checked for them at all (only budget/baggage/connection-
preference/dates/travelers/accessibility were ever covered).

Fixed: two new line-builders (_flight_departure_line/_flight_landing_
lines, mirroring _destination_gateway_summary's own per-code fact format -
including the same verified-vs-extended-catalog city_he distinction as
_verified_catalog_display_name) plus three new presence checks appended
to the existing missing-lines backfill.

Run: python3 tools/qa_dryrun5c_summary_missing_airport_lines.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import ariella_chat_clean as chat  # noqa: E402

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


HAMBURG_STATE = {
    "departure_airport": "TLV",
    "destination_airports": ["HAM"],
    "destination": {"places": ["המבורג"], "mode": "specific", "status": "known"},
    "dates": {"departure": "2027-05-07", "return": "2027-05-11", "needs_confirmation": False},
    "travelers": {"adults": 2, "children": 0},
    "flight": {"baggage": ["carry_on_only"], "connection_preference": "אין העדפה"},
    "budget_per_person": {"amount": 1200, "currency": "ILS"},
}

# The exact live-shaped broken reply - no יציאה/נחיתה/המראה בחזרה at all.
BROKEN_REPLY = (
    "מצוין, הטיסה עכשיו\n\n"
    "תקציב לאדם: 1200 שקלים\n"
    "כבודה: טרולי 8-10 ק\"ג לכל נוסע (בהתאם לתנאי חברת התעופה)\n"
    "תאריכים: 07.05.2027 - 11.05.2027\n"
    "נוסעים: 2 מבוגרים\n"
    "העדפת טיסה: אין העדפה לטיסה ישירה\n"
    "אם כל שאר הפרטים נכונים, כתבי מאשרת."
)

fixed = chat._ensure_flight_summary_completeness(BROKEN_REPLY, HAMBURG_STATE)
check("scenario D repro: the backfilled summary now includes the departure line (יציאה:)",
      "יציאה:" in fixed)
check("scenario D repro: the departure line names the real airport (TLV -> נתב״ג)",
      chat._flight_departure_line(HAMBURG_STATE) in fixed)
check("scenario D repro: the backfilled summary now includes the landing line (נחיתה:)",
      "נחיתה: המבורג (HAM), גרמניה" in fixed)
check("scenario D repro: the backfilled summary now includes the return-departure line (המראה בחזרה:)",
      "המראה בחזרה: המבורג (HAM), גרמניה" in fixed)
check("regression: the already-present budget/travelers/connection-preference lines are untouched, "
      "and the dates/baggage lines are still rebuilt in their own existing canonical format",
      "תקציב לאדם: 1200 שקלים" in fixed
      and "נוסעים: 2 מבוגרים" in fixed
      and "העדפת טיסה: אין העדפה לטיסה ישירה" in fixed
      and "07.05.2027" in fixed and "11.05.2027" in fixed)
check("regression: the backfilled lines are inserted before the approval phrase, not after",
      fixed.index("יציאה:") < fixed.index("כתבי מאשרת"))

# Regression: a reply that ALREADY has all three lines is left untouched.
COMPLETE_REPLY = (
    "הנה הסיכום:\n\n"
    "יציאה: נתב\"ג (TLV)\n"
    "נחיתה: המבורג (HAM), גרמניה\n"
    "המראה בחזרה: המבורג (HAM), גרמניה\n"
    "תאריכים: 07.05.2027 - 11.05.2027\n"
    "נוסעים: 2 מבוגרים\n"
    "כבודה: טרולי 8-10 ק\"ג לכל נוסע\n"
    "העדפת טיסה: אין העדפה לטיסה ישירה\n"
    "תקציב לאדם: 1200 שקלים\n"
    "אם כל הפרטים נכונים, כתבי מאשרת."
)
unchanged = chat._ensure_flight_summary_completeness(COMPLETE_REPLY, HAMBURG_STATE)
check("regression: a reply that already has all airport lines is never duplicated",
      unchanged.count("יציאה:") == 1 and unchanged.count("נחיתה:") == 1 and unchanged.count("המראה בחזרה:") == 1)

# Regression: a reply with no approval phrase at all (not a final summary
# turn) is never touched by this whole function.
NOT_A_SUMMARY = "מעולה, אני אדאג לכך. מה התקציב שלכם לאדם לטיסה?"
check("regression: a reply with no approval phrase is never touched at all",
      chat._ensure_flight_summary_completeness(NOT_A_SUMMARY, HAMBURG_STATE) == NOT_A_SUMMARY)

# Regression: destination_airports not resolved yet - no landing/return
# lines can be built (nothing to back-fill, never crashes).
STATE_NO_DEST = dict(HAMBURG_STATE, destination_airports=[])
check("regression: no destination_airports resolved -> landing/return lines are both None, no crash",
      chat._flight_landing_lines(STATE_NO_DEST) == (None, None))

# Direct unit coverage: _flight_departure_line / _flight_landing_lines.
check("_flight_departure_line builds the canonical line from a real code",
      chat._flight_departure_line({"departure_airport": "TLV"}) == f'יציאה: {chat.AIRPORT_NAMES["TLV"]} (TLV)')
check("_flight_departure_line returns None with no departure_airport at all",
      chat._flight_departure_line({}) is None)
check("_flight_landing_lines mirrors _destination_gateway_summary's own verified-vs-extended "
      "catalog distinction (ZAD, extended-only, uses city_en 'Zadar' not its own unverified "
      "city_he 'זאדאר')",
      chat._flight_landing_lines({"destination_airports": ["ZAD"]})[0] == "נחיתה: Zadar (ZAD), קרואטיה")


if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DRYRUN5C-SUMMARY-MISSING-AIRPORT-LINES TESTS PASSED")
