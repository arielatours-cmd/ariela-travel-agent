"""QA for Shlomo's relay of Carmit's work order item 2 (20.10.2026):
"אישורים מיותרים בשיחת טיסה" - matching qa/stage-scenarios.md's own
standing stage-1 failure-criteria table row:

| אישורים מיותרים | פרטים מפורשים: מספר נוסעים, תקציב, כבודה | "רק לוודא…" על פרט שנאמר במפורש |

TINKERBELL_SYSTEM already forbade re-asking a known fact outright (e.g.
"כמה אתם? (זוג עם ילדה בת 17, נכון?)") and already named travelers/budget/
baggage specifically in the "decision stays valid forever across domain
switches" rule - but the "check state before any question about X" rule's
own explicit field list named only dates/travelers/departure_airport/
flight/lodging/car/route, never תקציב/כבודה by name, and nothing before
this fix addressed the specific shape Shaked's table row calls out: a
"just to confirm" / "רק לוודא" phrasing used to RE-CONFIRM an explicit,
unambiguous fact (not to resolve a genuine ambiguity, which remains a
legitimate use of the same phrase - see the pre-existing weekday-conflict
messages at lines ~431/533, deliberately left untouched).

This is a pure TINKERBELL_SYSTEM (free-form conversational prompt) fix,
not a deterministic code path - there is nothing to unit-test behaviorally
without mocking the model's own free text. Mirrors the established pattern
for this kind of fix (e.g. tools/qa_stage1_run2_baggage_and_post_flight_
race.py's own TINKERBELL_SYSTEM substring checks): verify the exact wording
was added/extended and that the pre-existing, still-legitimate "רק לוודא"
usages for genuine ambiguity were left alone.

Run: python3 tools/qa_unnecessary_flight_confirmations.py
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


# =====================================================================
# The "check state before asking" rule's explicit field list must now
# name budget and baggage by name, not rely on the vague "טיסה" bucket -
# exactly the two fields Shaked's table row calls out alongside travelers
# count (already covered by "מספר נוסעים").
# =====================================================================
_state_check_rule = next(
    (line for line in chat.TINKERBELL_SYSTEM.splitlines()
     if "בדקי קודם את מצב החופשה המצטבר" in line),
    "",
)
check("the 'check state before any question' rule's own field list now "
      "names 'תקציב' (budget) explicitly",
      "תקציב" in _state_check_rule)
check("the 'check state before any question' rule's own field list now "
      "names 'כבודה' (baggage) explicitly",
      "כבודה" in _state_check_rule)
check("the field list still names travelers count (regression)",
      "מספר נוסעים" in _state_check_rule)

# =====================================================================
# The new rule explicitly treats a "רק לוודא"-phrased re-confirmation of
# an explicit, unambiguous fact as the same forbidden re-ask - not just a
# bare repeated question.
# =====================================================================
check("TINKERBELL_SYSTEM explicitly forbids 'רק לוודא' phrasing used to "
      "re-confirm an already-explicit fact (not just a bare re-ask)",
      'רק לוודא' in chat.TINKERBELL_SYSTEM
      and "מנוסחת כווידוא" in chat.TINKERBELL_SYSTEM)
check("the new rule gives a concrete forbidden budget re-confirmation "
      "example",
      "התקציב לטיסה הוא עד 3,000" in chat.TINKERBELL_SYSTEM)
check("the new rule gives a concrete forbidden baggage re-confirmation "
      "example",
      "אתם לוקחים גם מזוודה בבטן המטוס?" in chat.TINKERBELL_SYSTEM)

# =====================================================================
# Regression: the new rule must carve out genuine ambiguity (the
# weekday-conflict case) as still legitimate - it must not blanket-forbid
# every "רק לוודא" use, only ones confirming an explicit, unambiguous
# fact. The rule's own text must state the distinction explicitly.
# =====================================================================
check("the new rule explicitly preserves genuine-ambiguity confirmations "
      "(e.g. a weekday/date mismatch) as still legitimate",
      "סתירה/עמימות ממשית" in chat.TINKERBELL_SYSTEM
      or "עמימות אמיתית" in chat.TINKERBELL_SYSTEM)

# The pre-existing deterministic weekday-conflict messages are a genuine,
# still-legitimate use of "רק לוודא" (real ambiguity: stated date vs.
# stated weekday disagree) - confirm the code generating them is untouched.
import inspect
_src = inspect.getsource(chat)
check("regression: the deterministic weekday-conflict 'רק לוודא' messages "
      "(genuine date/weekday ambiguity, not an explicit-fact re-ask) are "
      "still present and untouched",
      _src.count('רק לוודא') >= 3)  # the two pre-existing weekday messages + the new rule's own text

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL UNNECESSARY-FLIGHT-CONFIRMATIONS TESTS PASSED")
