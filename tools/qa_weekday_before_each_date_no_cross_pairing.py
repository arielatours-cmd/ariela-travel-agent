"""QA for Shaked's live repro while regression-testing PR #54 (business
owner's manual WhatsApp test, Croatia, 16.10.2026): a deterministic false
weekday-conflict alarm that poisoned the whole conversation.

Message: "אני רוצה לטוס לקרואטיה ביום ראשון 19.9 עד חמישי 30.9" - both
weekdays are genuinely correct (19.9.2027 really is Sunday, 30.9.2027
really is Thursday), yet _weekday_date_conflict returned a false alarm:
"19.9.2027 יוצא יום ראשון, אבל כתבת יום חמישי". Ariella then kept
insisting 30.9.2027 was Wednesday even after the customer corrected her,
since the false claim had already entered the conversation history.

Root cause (original, "weekday DATE" phrasing): the function paired a
weekday with the nearest date via a one-directional scan. A first patch
added a SECOND, reverse (date-then-weekday) scan for that phrasing, with a
guard rejecting a date-then-weekday match whenever the matched weekday was
itself followed shortly by its own date.

Shaked then found the SAME bug in the opposite, "DATE (weekday)" phrasing
family - "19.9 (ראשון) עד 30.9 (חמישי)", "19.9 ראשון עד 30.9 חמישי", "19.9
ראשון - 30.9 חמישי" - where the original forward (weekday-then-date) scan
wrongly skipped past the date immediately BEHIND a weekday and paired it
with the far date ahead instead, and the reverse scan's own guard then
rejected the correct pairing too (since that weekday IS followed shortly by
its own, separate date - the one belonging to the NEXT weekday). No fixed
scan direction (or one-off guard patch) works for every phrasing.

Fixed with a redesign: for each weekday mention, independently find the
nearest date on EITHER side (within 40 chars) and pair with whichever is
closer - no directional scan, no special-casing by format.

Run: python3 tools/qa_weekday_before_each_date_no_cross_pairing.py
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


check("exact live repro: no false alarm when both weekdays are genuinely correct",
      chat._weekday_date_conflict("אני רוצה לטוס לקרואטיה ביום ראשון 19.9 עד חמישי 30.9", []) is None)

check("same shape, different correct dates: still no false alarm",
      chat._weekday_date_conflict("ביום שני 20.9 עד שישי 24.9", []) is None)

# --- Regressions: a genuine conflict on either date must still be caught ---
r1 = chat._weekday_date_conflict("אני רוצה לטוס ביום שלישי 19.9 עד חמישי 30.9", [])
check("regression: a genuine conflict on the FIRST date is still caught",
      bool(r1) and "19.9" in r1)

r2 = chat._weekday_date_conflict("אני רוצה לטוס ביום ראשון 19.9 עד שני 30.9", [])
check("regression: a genuine conflict on the SECOND date is still caught",
      bool(r2) and ("30.9" in r2 or "30.09" in r2))

check("regression: a single weekday+date pair with a real conflict is still caught",
      bool(chat._weekday_date_conflict("יום שני 15/07/2027", [])))

check("regression: two children's ages ('שני ילדים') never false-trigger",
      chat._weekday_date_conflict(
          "תאילנד, אני ובעלי ושני ילדים בני 8 ו-11, 15/07/2027 עד 29/07/2027", []
      ) is None)

# --- Shaked's second finding: the opposite "DATE (weekday)" phrasing
# family, where the date each weekday belongs to sits BEHIND it, not
# ahead - all genuinely correct, must never false-alarm. ---
check("DATE (weekday) with parens: no false alarm",
      chat._weekday_date_conflict(
          "אני רוצה לטוס לקרואטיה 19.9 (ראשון) עד 30.9 (חמישי)", []
      ) is None)
check("DATE weekday, no parens: no false alarm",
      chat._weekday_date_conflict(
          "אני רוצה לטוס לקרואטיה 19.9 ראשון עד 30.9 חמישי", []
      ) is None)
check("DATE weekday with a dash separator: no false alarm",
      chat._weekday_date_conflict(
          "אני רוצה לטוס לקרואטיה 19.9 ראשון - 30.9 חמישי", []
      ) is None)

# --- Regression: a genuine conflict in the "DATE (weekday)" family must
# still be caught, not swallowed by the redesign. ---
r3 = chat._weekday_date_conflict("אני רוצה לטוס 19.9 (שלישי) עד 30.9 (חמישי)", [])
check("regression: a genuine conflict in the DATE (weekday) family is still caught",
      bool(r3) and "19.9" in r3)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL WEEKDAY-BEFORE-EACH-DATE-NO-CROSS-PAIRING TESTS PASSED")
