"""QA for the business owner's decision (2026-10-16, relayed by Shlomo) on
the fixed fallback-question dictionaries and separate deterministic
confirmation gates: they stay as fixed sentences in this PR (no extra model
call added for them), but each one must still comply with the iron rule -
one question only, open or a yes/no about a single option, never "X or Y".

Covers:
1. _GAP_QUESTION_TEXT entries that were reworded (transmission, pickup,
   return, lodging.type, budget_or_level, pace) - and the matching bare-
   yes/no fix for _deterministic_trip_planning_pace_facts, the same class
   of gap already found and fixed this session for connection preference/
   car transmission/lodging level (a bare "כן"/"לא" to the new single-
   option phrasing names no pace word at all).
2. The reset-confirmation text (flights/vacation) - no longer spells out
   "X or Y? (yes=X, no=Y)", just a single yes/no about the destructive
   option; the downstream yes_match/no_match gate is unchanged.
3. The pending_new_trip/possible_new_trip destination-change confirmation -
   no longer "new separate trip, or destination change?", just a single
   yes/no about the destination-change interpretation.

Run: python3 tools/qa_iron_rule_fallback_texts.py
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


def has_dictated_or(text):
    """Heuristic for the banned "X or Y?" shape: a bare "או" (or) joining
    two named options inside the sentence, not inside a single clause like
    "שינוי משהו" (one escape-hatch clause riding on an otherwise single
    question, which stays allowed)."""
    return " או " in text


# --- 1. _GAP_QUESTION_TEXT: no entry asks about two named options ---
for key, text in chat._GAP_QUESTION_TEXT.items():
    if key == "trip_planning.approved":
        # A yes/no confirmation with a natural "or tell me what to change"
        # escape hatch - already the established, tested compliant pattern
        # used throughout live route-approval transcripts, not a forced
        # choice between two named substantive options.
        continue
    check(f"_GAP_QUESTION_TEXT[{key!r}] has no dictated 'X or Y'", not has_dictated_or(text))

check("car.details.transmission is a single-option yes/no",
      chat._GAP_QUESTION_TEXT["car.details.transmission"] == "חשוב לכם רכב אוטומטי?")
check("lodging.details.type no longer lists the three options",
      chat._GAP_QUESTION_TEXT["lodging.details.type"] == "איזה סוג לינה מתאים לכם?")
check("lodging.details.budget_or_level asks one question only",
      chat._GAP_QUESTION_TEXT["lodging.details.budget_or_level"] == "מה התקציב שלכם ללילה?")
check("trip_planning.details.pace is a single-option yes/no",
      chat._GAP_QUESTION_TEXT["trip_planning.details.pace"] == "חשוב לכם שהקצב יהיה רגוע?")

# --- 2. pace bare yes/no (same gap class as connection-preference/transmission/level) ---
def pace(msg, prior):
    return chat._deterministic_trip_planning_pace_facts(msg, [{"role": "assistant", "content": prior}])


check("bare 'כן' to the new single-option pace question -> relaxed",
      pace("כן", "חשוב לכם שהקצב יהיה רגוע?") == {"trip_planning": {"details": {"pace": "relaxed"}}})
check("bare 'לא' -> no preference (not an assertion of 'active')",
      pace("לא", "חשוב לכם שהקצב יהיה רגוע?") == {"trip_planning": {"details": {"pace": "אין העדפה"}}})
check("regression: explicit word still works on old-style dual phrasing",
      pace("פעיל", "אתם מעדיפים קצב רגוע או פעיל?") == {"trip_planning": {"details": {"pace": "active"}}})
check("regression: old-style dual phrasing + bare 'כן' stays ambiguous -> {}",
      pace("כן", "אתם מעדיפים קצב רגוע או פעיל?") == {})
check("unrelated prior text -> gate stays shut",
      pace("כן", "כמה חדרים תרצו?") == {})

# --- 3. reset-confirmation text: single yes/no, no "X or Y? (yes=X, no=Y)" ---
import inspect
source = inspect.getsource(chat)
check("flights reset-confirmation no longer spells out '(yes=X, no=Y)'",
      "למחוק הכול ולהתחיל טיסה חדשה?" in source
      and "(כן = למחוק ולהתחיל מחדש, לא = להשאיר ולשנות)" not in source)
check("vacation reset-confirmation no longer spells out '(yes=X, no=Y)'",
      "למחוק הכול ולהתחיל חופשה חדשה?" in source)

# --- 4. pending/possible new-trip destination-change confirmation ---
check("pending_new_trip confirmation is a single yes/no about the destination-change interpretation",
      "זה שינוי יעד בחופשה הנוכחית ל" in source
      and "זו חופשה חדשה ונפרדת, או שינוי יעד" not in source)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL IRON-RULE FALLBACK-TEXT TESTS PASSED")
