"""QA for Shlomo's relay (20.10.2026, live finding on main@30e07e1, prior to
PR #91): r90a2, Bari - a reply to the customer ended with a trailing Hebrew
parenthetical that was clearly an internal planning note never meant for the
customer ("(לפני התשובה הבאה: נותר לברר תקציב ולינה)"), not a translated
internal-terminology leak (that's the pre-existing, differently-shaped
_strip_leaked_internal_paragraph/#90 fix - a LEADING paragraph, usually with
a script/casing signature of non-Hebrew origin). This leak is a native-Hebrew
TRAILING note, so it needed its own narrow filter rather than widening the
existing one.

First attempt (merged into PR #94 before Shaked's review): gated on a fixed
list of marker phrases ("לפני התשובה הבאה", "בתשובה הבאה", "note to self",
etc.) - exactly the phrase-list pattern the business owner forbids as a
primary mechanism. Shaked's regression review found two real leaked notes
that slipped straight past it simply by using different wording or a
different bracket style:
- "(עדיין חסר: תקציב וכבודה, לשאול בהמשך)" - no marker phrase matched.
- "[הערה פנימית: לשאול אחר כך על כבודה]" - square brackets, not parentheses.

Fixed: _strip_leaked_planning_parenthesis(text, injected_guidance) now
strips a trailing parenthetical/bracketed note - any wording, either bracket
style - only when BOTH hold, neither a guessed/fixed trigger phrase:
1. it has the colon-separated "note:" shape every real leak has (a
   structural pattern, not specific wording) - a genuine customer-facing
   aside never has one;
2. its own content shares real vocabulary (substring-level, to survive
   Hebrew prefixes like ו-/ה-) with injected_guidance - the ACTUAL
   system_dynamic text injected into the model's prompt THIS turn - so a
   genuine leak (echoing the model's own real guidance back) is caught
   regardless of its exact phrasing, while a customer-facing aside that
   shares no such vocabulary is never touched.

_call_tinkerbell now passes its own system_dynamic (the real per-turn
prompt text) as injected_guidance at the call site.

Run: python3 tools/qa_bari_planning_leak.py
"""
import os
import sys
import inspect

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import ariella_chat_clean as chat

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# A representative per-turn guidance blob - approximates what system_dynamic
# actually contains for a Bari-like turn (budget/baggage still pending,
# destination resolved, no verified direct route). The direct-route segment
# below is the REAL output of _direct_route_hint_text for exactly this
# shape of state, not a hand-typed guess.
_state_no_direct_route = {
    "destination": {"places": ["בארי"]}, "destination_airports": ["BRI"],
    "lodging": {}, "budget_amount": None,
}
assert not chat._direct_route_available(_state_no_direct_route), "test setup: BRI must have no known direct route in the catalog"
_real_direct_route_hint = chat._direct_route_hint_text(_state_no_direct_route)
# The real call site always includes the raw state JSON dump unconditionally
# (system_dynamic's '\nמצב החופשה המצטבר שכבר ידוע:\n' + _state_context(...)
# segment) - this is what gives an English-phrased leak ("lodging",
# "budget") something real to overlap with, via literal field names, not
# because this test guessed English words would appear.
GUIDANCE = (
    "מצב החופשה המצטבר שכבר ידוע: תקציב: עדיין לא נקבע. כבודה: עדיין לא נקבעה. "
    + _real_direct_route_hint
    + chat._state_context(_state_no_direct_route)
)
check("the representative guidance blob genuinely contains the real "
      "_direct_route_hint_text output (not a hand-typed guess)",
      _real_direct_route_hint and _real_direct_route_hint in GUIDANCE)

# =====================================================================
# Direct unit tests of the new filter, against the two leaks Shaked found
# that slipped past the first (marker-phrase-list) version.
# =====================================================================
_leak_new_wording = "בארי זו עיר נהדרת! (עדיין חסר: תקציב וכבודה, לשאול בהמשך)"
check("a leaked note using DIFFERENT wording than any hardcoded marker "
      "('עדיין חסר: ...') is still stripped, because it shares real "
      "vocabulary (תקציב/כבודה) with the actual injected guidance",
      chat._strip_leaked_planning_parenthesis(_leak_new_wording, GUIDANCE)
      == "בארי זו עיר נהדרת!")

_leak_square_brackets = "מעולה, קלטתי. [הערה פנימית: לשאול אחר כך על כבודה]"
check("a leaked note in SQUARE BRACKETS (not parentheses at all) is now "
      "caught too",
      chat._strip_leaked_planning_parenthesis(_leak_square_brackets, GUIDANCE)
      == "מעולה, קלטתי.")

# =====================================================================
# Regression: the original marker-phrased leak must still be caught (now
# via genuine content overlap with the real direct-route hint text, not a
# marker match).
# =====================================================================
_leak_orig = (
    "בארי זו עיר נהדרת בדרום איטליה! (לפני התשובה הבאה: נותר לברר אם יש "
    "הגבלת תקציב לטיסה, וחשוב לציין שאין עדיין טיסה ישירה מאומתת ליעד הזה)"
)
check("regression: the original Bari leak (marker phrasing) is still stripped",
      chat._strip_leaked_planning_parenthesis(_leak_orig, GUIDANCE)
      == "בארי זו עיר נהדרת בדרום איטליה!")

_leak_english = "סבבה! (note to self: still need lodging + budget before summary)"
check("regression: an English-phrased leak is still caught, via overlap "
      "with the literal English field names ('lodging', 'budget') the raw "
      "state JSON dump always contributes to the real injected guidance - "
      "not via 'note to self' as a marker phrase",
      chat._strip_leaked_planning_parenthesis(_leak_english, GUIDANCE) == "סבבה!")

# =====================================================================
# Regression: genuine customer-facing asides, including ones that happen to
# mention a topic word also present in the guidance, must never be touched
# unless they also have the colon-note shape.
# =====================================================================
_clean_direct_flight = "מצאתי טיסה ישירה (שאוליי תעדיפו) ליעד המבוקש."
check("regression: a normal customer-relevant parenthetical ('טיסה ישירה') "
      "is left untouched",
      chat._strip_leaked_planning_parenthesis(_clean_direct_flight, GUIDANCE)
      == _clean_direct_flight)

_clean_weekday = "התאריכים הם 10-17 ביוני (יום חמישי עד יום חמישי)."
check("regression: a weekday-clarification parenthetical is left untouched",
      chat._strip_leaked_planning_parenthesis(_clean_weekday, GUIDANCE) == _clean_weekday)

_clean_breakfast = "כלול ארוחת בוקר (ללא תוספת תשלום)."
check("regression: an ordinary trailing aside with no colon at all is left "
      "untouched, even though this exact filter call has nothing to do "
      "with its words",
      chat._strip_leaked_planning_parenthesis(_clean_breakfast, GUIDANCE) == _clean_breakfast)

_clean_mentions_topic_no_colon = "מצוין! (תקציב וכבודה כבר נקלטו)"
check("regression: a trailing note that happens to share real vocabulary "
      "with the guidance (תקציב/כבודה) but has NO colon-note shape is left "
      "untouched - content overlap alone is never enough",
      chat._strip_leaked_planning_parenthesis(_clean_mentions_topic_no_colon, GUIDANCE)
      == _clean_mentions_topic_no_colon)

check("regression: a plain reply with no parentheses/brackets at all is "
      "returned unchanged",
      chat._strip_leaked_planning_parenthesis("תשובה רגילה בלי סוגריים.", GUIDANCE)
      == "תשובה רגילה בלי סוגריים.")

check("regression: empty/None input never raises",
      chat._strip_leaked_planning_parenthesis(None, GUIDANCE) == ""
      and chat._strip_leaked_planning_parenthesis("", GUIDANCE) == "")

check("regression: a mid-text legitimate parenthetical before a leaked "
      "TRAILING one is untouched - only the trailing note is ever removed",
      chat._strip_leaked_planning_parenthesis(
          "בארי מקסימה! (טיסה ישירה) (לפני התשובה הבאה: נותר לברר תקציב)",
          GUIDANCE,
      ) == "בארי מקסימה! (טיסה ישירה)")

# =====================================================================
# TINKERBELL_SYSTEM rule + post-processing wiring.
# =====================================================================
check("TINKERBELL_SYSTEM forbids writing what remains to find out / what "
      "will be asked next",
      "נותר לברר" in chat.TINKERBELL_SYSTEM and "note to self" in chat.TINKERBELL_SYSTEM)

_tinkerbell_src = inspect.getsource(chat._call_tinkerbell)
check("_call_tinkerbell's post-processing chain calls "
      "_strip_leaked_planning_parenthesis right after "
      "_strip_leaked_internal_paragraph, passing its own system_dynamic as "
      "the actual injected guidance text",
      "reply = _strip_leaked_internal_paragraph(reply)" in _tinkerbell_src
      and "reply = _strip_leaked_planning_parenthesis(reply, system_dynamic)" in _tinkerbell_src
      and _tinkerbell_src.index("_strip_leaked_internal_paragraph(reply)")
      < _tinkerbell_src.index("_strip_leaked_planning_parenthesis(reply, system_dynamic)"))

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL BARI-PLANNING-LEAK TESTS PASSED")
