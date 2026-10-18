"""QA for _mentions_a_different_place - the shared helper extracted per the
business owner's explicit instruction (2026-10-15, via Shlomo/Ofek, after
round 2's recurring cross-vacation-contamination findings C1/C3/B2 and
A7's reopen-recognition gap): stop reinventing one-off "does this message
still mean the same trip" mention-matching logic at every gate; have them
share one tested function instead.

Run: python3 tools/qa_mentions_a_different_place_helper.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()
import ariella_chat_clean as chat

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


check("mentioning only the known place is never 'a different place'",
      not chat._mentions_a_different_place("אני רוצה שוב טיסה לרומא", ["רומא"]))
check("naming the old place only to say 'separate from it' IS a different place (Amsterdam)",
      chat._mentions_a_different_place("יש לי עוד נסיעת עסקים, לאמסטרדם, נפרדת מברלין", ["ברלין"]))
check("a bare unrelated message with no place at all is never 'a different place'",
      not chat._mentions_a_different_place("היי, אני רוצה עוד טיסה", ["רומא"]))
check("an explicit different destination with no mention of the old one at all IS a different place",
      chat._mentions_a_different_place("רוצה לתכנן חופשה חדשה לברצלונה", ["רומא"]))
check("no known_places at all (empty trip) - any mentioned place counts as different",
      chat._mentions_a_different_place("טיסה לאיטליה", []))

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL MENTIONS-A-DIFFERENT-PLACE-HELPER TESTS PASSED")
