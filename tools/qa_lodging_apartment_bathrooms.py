"""QA for the business owner's instruction (2026-10-16, relayed by Shlomo):
"בחיפוש דירות - במקרה של דירה ולא מלון - לשאול כמה חדרי רחצה נדרשים" (for
apartment searches - not hotels - ask how many bathrooms are needed).

Added as a principle in TINKERBELL_SYSTEM (not a fixed phrasing, asked in
its own separate question per the one-option-per-question rule), and as a
deterministic safety-net writer for lodging.details.bathrooms, mirroring
the existing rooms/level writers so a short numeric answer is never lost
to a silent extractor miss.

Search/filter integration (SerpApi vacation-rentals bathroom parameter or
client-side filtering) is explicitly deferred past this PR per the same
instruction ("את החלק הזה אפשר לעשות אחרי תיקון שלב 1") - not covered here.

Run: python3 tools/qa_lodging_apartment_bathrooms.py
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


def lodging(msg, prior):
    return chat._deterministic_lodging_facts(msg, [{"role": "assistant", "content": prior}])


check("a numeric answer to a freely-worded bathrooms question is captured",
      lodging("2", "כמה חדרי רחצה תרצו בדירה?") == {"lodging": {"details": {"bathrooms": 2}}})
check("a number embedded in a longer sentence is still captured",
      lodging("אנחנו צריכים 3 חדרי רחצה בבקשה", "כמה חדרי רחצה תרצו?") == {"lodging": {"details": {"bathrooms": 3}}})
check("'אין העדפה' to the bathrooms question is captured as no preference",
      lodging("אין העדפה", "כמה חדרי רחצה תרצו בדירה?") == {"lodging": {"details": {"bathrooms": "אין העדפה"}}})
check("the gate does not fire on the unrelated rooms question",
      lodging("2", "כמה חדרים תרצו?") == {})
check("the gate does not fire on unrelated prior text",
      lodging("2", "מה התקציב שלכם ללילה?") == {})

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL LODGING-APARTMENT-BATHROOMS TESTS PASSED")
