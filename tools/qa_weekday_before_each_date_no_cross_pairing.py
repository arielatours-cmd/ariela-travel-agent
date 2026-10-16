"""QA for Shaked's live repro while regression-testing PR #54 (business
owner's manual WhatsApp test, Croatia, 16.10.2026): a deterministic false
weekday-conflict alarm that poisoned the whole conversation.

Message: "אני רוצה לטוס לקרואטיה ביום ראשון 19.9 עד חמישי 30.9" - both
weekdays are genuinely correct (19.9.2027 really is Sunday, 30.9.2027
really is Thursday), yet _weekday_date_conflict returned a false alarm:
"19.9.2027 יוצא יום ראשון, אבל כתבת יום חמישי". Ariella then kept
insisting 30.9.2027 was Wednesday even after the customer corrected her,
since the false claim had already entered the conversation history.

Root cause: the function pairs a weekday with the NEAREST date on either
side within 40 characters. Its weekday-then-date scan correctly found both
real pairs (ראשון+19.9, חמישי+30.9). But its REVERSE date-then-weekday scan
then also matched date=19.9 with the weekday "חמישי" - the nearest weekday
token textually following 19.9 - even though that weekday actually belongs
to the LATER date (30.9) immediately after it, not to 19.9. Fixed by
rejecting a date-then-weekday match whenever the matched weekday is itself
followed shortly by a date of its own (meaning it is the leading weekday of
THAT date, not the trailing weekday of the one before it).

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

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL WEEKDAY-BEFORE-EACH-DATE-NO-CROSS-PAIRING TESTS PASSED")
