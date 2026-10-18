"""QA for the #2-priority bug from Shaked's round-14 QA run (2026-10-14,
qa/reports/2026-10-14-round14.md on the shaked branch, scenarios C1/C2):
after the customer explicitly said "לא ניו יורק. חופשת סקי חדשה לאינסברוק"
and later "חופשה חדשה. אל תמחקי את ניו יורק" (don't delete New York) and
confirmed the reset gate, Ariella opened "מתחילים חופשה חדשה לניו יורק" -
the exact OLD trip the customer had just explicitly ruled out / said to
keep untouched, instead of Innsbruck, the destination she'd actually asked
for.

Root cause traced directly in _deterministic_destination_facts: it is a
naive substring search over every known place name, with zero negation
awareness - "ניו יורק" appearing anywhere in the text (even inside "אל
תמחקי את ניו יורק" or "לא ניו יורק") was picked up as THE destination,
regardless of grammatical context. Fixed with _is_negated_destination_mention:
a place name is skipped when it's immediately preceded (within a short
window) by "don't delete/keep X" phrasing or a bare "לא X" ("not X")
directly adjacent to it - while a place mentioned normally elsewhere in the
same message (even alongside an unrelated "לא") is still picked up.

Run: python3 tools/qa_destination_negation_extraction.py
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


def _places(message):
    result = chat._deterministic_destination_facts([], message, {})
    return ((result.get("destination") or {}).get("places") or []) if result else []


# --- 1. The exact live bug, part A: bare "לא <place>" rejection, with the
#        real new destination stated right after in the same message ---
check("'לא ניו יורק. חופשת סקי חדשה לאינסברוק' extracts Innsbruck, not New York",
      _places("לא ניו יורק. חופשת סקי חדשה לאינסברוק") == ["אינסברוק"])

# --- 2. The exact live bug, part B: "don't delete X" phrasing extracts
#        nothing (safely asks again) rather than wrongly picking X ---
check("'אל תמחקי את ניו יורק' alone extracts no destination (never New York)",
      _places("חופשה חדשה. אל תמחקי את ניו יורק") == [])

# --- 3. A normal, unnegated destination mention still works exactly as
#        before ---
check("a plain destination mention still extracts normally",
      _places("אני רוצה לטוס לרומא") == ["רומא"])

# --- 4. A negated place AND a genuine new destination in the same message -
#        the real one must still be found, the negated one skipped ---
check("negated place + real destination in the same message: the real one wins",
      _places("אל תמחקי את ניו יורק, אני רוצה לטוס לרומא") == ["רומא"])

# --- 5. An unrelated "לא" elsewhere in the message (not immediately before
#        the place name) must never suppress a genuine destination mention -
#        this is the main false-positive risk of the fix ---
check("an unrelated 'לא' elsewhere in the message doesn't block a real destination",
      _places("לא רוצה תקציב מוגבל, לטוס לרומא") == ["רומא"])

# --- 6. Defensive: empty/None message never crashes ---
check("empty message never crashes", _places("") == [])
check("None-ish message never crashes", chat._deterministic_destination_facts([], None, {}) == {})

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DESTINATION-NEGATION-EXTRACTION TESTS PASSED")
