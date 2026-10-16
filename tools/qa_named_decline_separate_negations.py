"""QA for bug #3 (Shaked, qa-s97, round 7, focused conversation-flow pass,
2026-10-16): "לא צריך לינה ולא רכב" (don't need lodging and not car) only
declined lodging - car kept being asked about ("איזה סוג/גודל רכב?"),
repeating for a fourth consecutive round in that conversation (A3).

Root cause: _deterministic_named_decline_facts in ariella_chat_clean.py
only recognized two shapes: one shared negation in front of a coordinated
list ("לא צריך לינה ורכב"), or a standalone "בלי X"/"ללא X" per service.
Neither covers two services each negated SEPARATELY with their own "לא"
("לא צריך לינה ולא רכב") - exactly how Hebrew naturally elides the
repeated need-word (the full, non-elided form "לא צריך לינה ולא צריך
רכב" was ALSO silently broken the same way, since that shape wasn't
recognized either).

Fixed: after the first declined service, any further "ולא (need-word)?
SERVICE" in the same clause - with or without repeating the need-word -
is itself an unambiguous decline of that service.

Run: python3 tools/qa_named_decline_separate_negations.py
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


def decline(message):
    return chat._deterministic_named_decline_facts(message)


# --- Shaked's exact live repro ---
check("'לא צריך לינה ולא רכב' declines BOTH lodging and car",
      decline("לא צריך לינה ולא רכב").get("session_status") == {"lodging": "declined", "car": "declined"})
check("the feminine form 'לא צריכה לינה ולא רכב' works the same way",
      decline("לא צריכה לינה ולא רכב").get("session_status") == {"lodging": "declined", "car": "declined"})
check("the fully repeated form 'לא צריך לינה ולא צריך רכב' also works",
      decline("לא צריך לינה ולא צריך רכב").get("session_status") == {"lodging": "declined", "car": "declined"})
check("a third chained negation ('ולא לינה') is also picked up",
      decline("לא צריך מסלול ולא רכב ולא לינה").get("session_status")
      == {"trip_planning": "declined", "car": "declined", "lodging": "declined"})

# --- Regression guards: every existing qa/cases.json case for this
#     function must keep passing exactly as before ---
check("regression: single masculine decline ('לא צריך מסלול כרגע')",
      decline("תחפשי בשניהם. לא צריך מסלול כרגע").get("session_status") == {"trip_planning": "declined"})
check("regression: 'רכב לא נדרש' (trailing negation, no 'לא...צריך' prefix)",
      decline("רכב לא נדרש").get("session_status") == {"car": "declined"})
check("regression: no false positive on an unrelated car-rental sentence",
      decline("אני רוצה לשכור רכב גדול כי אנחנו משפחה עם הרבה מזוודות") == {})
check("regression: coordinated list with one shared trailing negation",
      decline("לינה ורכב לא צריך, יש לנו איפה לישון").get("session_status") == {"lodging": "declined", "car": "declined"})
check("regression: 'בלי X ובלי Y, ולא צריך Z' (triple mixed shape)",
      decline("בלי מלון ובלי רכב, ולא צריך מסלול").get("session_status")
      == {"lodging": "declined", "car": "declined", "trip_planning": "declined"})

# --- Regression found by Shaked reviewing this exact change (PR #51,
#     2026-10-16): מלון/דירה/וילה/צימר/לינה are all "lodging", so a
#     same-service TYPE CONTRAST ("דירה ולא מלון") wrongly declined the
#     whole lodging service instead of just naming a type preference ---
check("'כן, דירה ולא מלון' is a type preference, not a lodging decline",
      decline("כן, דירה ולא מלון") == {})
check("'כן, צריך לינה - מלון ולא דירה' is a type preference, not a decline",
      decline("כן, צריך לינה - מלון ולא דירה") == {})

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL NAMED-DECLINE-SEPARATE-NEGATIONS TESTS PASSED")
