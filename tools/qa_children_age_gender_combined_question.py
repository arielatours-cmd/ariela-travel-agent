"""QA for the business owner's decision (2026-10-16, relayed by Shlomo,
correcting her own earlier instruction on this): child gender stays (saved
to the member profile alongside age, task 010a), but age and gender are
asked together in ONE open question, as a principle - never as two
separate questions, and never re-asking the age once it is already known.

Live bug (Croatia, trip 258, 16.10): child_ages was already saved
("9 ו-11" given at 15:52), yet at 16:10 Ariella asked again "עוד שתי
שאלות: ... ובת כמה ובן כמה הילדים (רק כדי לדעת את המגדר)?" - re-asking the
already-known ages just to get at the gender.

The business owner's FIRST fix attempt still allowed one follow-up
question about gender alone when only ages were known. She then EXPLICITLY
RETRACTED that part (same day): "גיל ומין הילדים נשאלים בשאלה אחת בלבד. אין
שאלת המשך נפרדת. אם הלקוח ענה רק עם גילאים, אריאלה לא שואלת שוב, וממשיכה
הלאה עם מה שיש." - no follow-up gender-only question is allowed at all,
ever; if gender wasn't given alongside age, Ariella proceeds without it.

This only checks the principle is present in TINKERBELL_SYSTEM and that
the existing travelers.child_ages gap computation (which already never
required gender) is unaffected - whether Tinkerbell's own free phrasing
follows the principle live is a model-behavior question outside what a
unit test can enforce.

Run: python3 tools/qa_children_age_gender_combined_question.py
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


prompt = chat.TINKERBELL_SYSTEM
check("prompt instructs asking age and gender together in one open question",
      "גיל ומגדר באותה שאלה פתוחה אחת" in prompt)
check("prompt explicitly forbids re-asking age once child_ages is already known",
      "לעולם אל תחזרי על שאלת הגיל כשהוא כבר ידוע" in prompt)
check("prompt's retraction is applied: NO gender-only follow-up question is allowed at all",
      "מותרת שאלת השלמה אחת על המגדר בלבד" not in prompt)
check("prompt explicitly forbids a separate follow-up question about gender",
      "אין שאלת המשך נפרדת על המגדר" in prompt)

# Regression: travelers.child_ages gap computation never required gender,
# and must still not after this prompt-only change (no code path touched).
state_ages_known_no_gender = {
    "requested_services": ["flights"],
    "travelers": {"adults": 2, "children": 2, "child_ages": [9, 11], "child_genders": [None, None]},
}
gaps = chat._required_state_gaps(state_ages_known_no_gender)
check("regression: missing gender alone is never a required gap",
      "travelers.child_ages" not in gaps and not any("gender" in g for g in gaps))

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL CHILDREN-AGE-GENDER-COMBINED-QUESTION TESTS PASSED")
