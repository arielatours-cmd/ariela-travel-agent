"""QA for Shlomo's relay (20.10.2026, live finding on main@30e07e1, prior to
PR #91): r90a2, Bari - a reply to the customer ended with a trailing Hebrew
parenthetical that was clearly an internal planning note never meant for the
customer ("(לפני התשובה הבאה: נותר לברר תקציב ולינה)"), not a translated
internal-terminology leak (that's the pre-existing, differently-shaped
_strip_leaked_internal_paragraph/#90 fix - a LEADING paragraph, usually with
a script/casing signature of non-Hebrew origin). This leak is a native-Hebrew
TRAILING parenthesis, so it needed its own narrow, marker-gated filter rather
than widening the existing one.

Fixed:
- A new TINKERBELL_SYSTEM rule, right after the existing internal-
  terminology rule, forbidding any "what's left to find out" / "what I'll
  ask next" sentence or parenthetical in the reply at all.
- A new _strip_leaked_planning_parenthesis(text) post-processing filter,
  gated on explicit unambiguous markers only ("לפני התשובה הבאה", "בתשובה
  הבאה", "לפני שאני עונה", "לפני שאשיב", "לפני שאמשיך", "הערה לעצמי",
  "note to self") - never a blanket "strip every parenthesis" rule, which
  would also eat a customer-relevant parenthetical ("(טיסה ישירה)").
- Wired into _call_tinkerbell's post-processing chain right after the
  existing _strip_leaked_internal_paragraph call.

Run: python3 tools/qa_bari_planning_leak.py
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
# Direct unit tests of the new filter.
# =====================================================================
_leak1 = "בארי זו עיר נהדרת בדרום איטליה! (לפני התשובה הבאה: נותר לברר תקציב ולינה)"
check("a trailing 'לפני התשובה הבאה' planning note is stripped entirely",
      "לפני התשובה הבאה" not in chat._strip_leaked_planning_parenthesis(_leak1)
      and "בארי זו עיר נהדרת בדרום איטליה!" in chat._strip_leaked_planning_parenthesis(_leak1))

_leak2 = "מעולה, קלטתי את התאריכים. (בתשובה הבאה אשאל על תקציב)"
check("a 'בתשובה הבאה' note-to-self parenthetical is stripped",
      "בתשובה הבאה" not in chat._strip_leaked_planning_parenthesis(_leak2))

_leak3 = "סבבה! (note to self: still need lodging + budget before summary)"
check("an English 'note to self' parenthetical is stripped too",
      "note to self" not in chat._strip_leaked_planning_parenthesis(_leak3))

_leak4 = "טסים לבארי בשמחה. (לפני שאשיב, אוודא שאין עוד שאלות פתוחות)"
check("'לפני שאשיב' is recognized as a planning-note marker",
      "לפני שאשיב" not in chat._strip_leaked_planning_parenthesis(_leak4))

# Regression: an ordinary, customer-relevant parenthetical must never be touched.
_clean1 = "מצאתי טיסה ישירה (שאוליי תעדיפו) ליעד המבוקש."
check("regression: a normal customer-relevant parenthetical ('טיסה ישירה') is left untouched",
      chat._strip_leaked_planning_parenthesis(_clean1) == _clean1)

_clean2 = "התאריכים הם 10-17 ביוני (יום חמישי עד יום חמישי)."
check("regression: a weekday-clarification parenthetical is left untouched",
      chat._strip_leaked_planning_parenthesis(_clean2) == _clean2)

check("regression: a plain reply with no parentheses at all is returned unchanged",
      chat._strip_leaked_planning_parenthesis("תשובה רגילה בלי סוגריים.") == "תשובה רגילה בלי סוגריים.")

check("regression: empty/None input never raises",
      chat._strip_leaked_planning_parenthesis(None) == ""
      and chat._strip_leaked_planning_parenthesis("") == "")

# Multiple markers/parens in the same reply - all leaked ones removed, nothing
# else disturbed.
_multi = "בארי מקסימה! (טיסה ישירה) (לפני התשובה הבאה: נותר לברר לינה)"
_multi_cleaned = chat._strip_leaked_planning_parenthesis(_multi)
check("a mix of a legitimate and a leaked parenthetical in the same reply: only the leaked one is removed",
      "(טיסה ישירה)" in _multi_cleaned and "לפני התשובה הבאה" not in _multi_cleaned)

# =====================================================================
# TINKERBELL_SYSTEM rule + post-processing wiring.
# =====================================================================
check("TINKERBELL_SYSTEM forbids writing what remains to find out / what will be asked next",
      "נותר לברר" in chat.TINKERBELL_SYSTEM and "note to self" in chat.TINKERBELL_SYSTEM)

import inspect
_tinkerbell_src = inspect.getsource(chat._call_tinkerbell)
check("_call_tinkerbell's post-processing chain calls _strip_leaked_planning_parenthesis "
      "right after _strip_leaked_internal_paragraph",
      "reply = _strip_leaked_internal_paragraph(reply)" in _tinkerbell_src
      and "reply = _strip_leaked_planning_parenthesis(reply)" in _tinkerbell_src
      and _tinkerbell_src.index("_strip_leaked_internal_paragraph(reply)")
      < _tinkerbell_src.index("_strip_leaked_planning_parenthesis(reply)"))

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL BARI-PLANNING-LEAK TESTS PASSED")
