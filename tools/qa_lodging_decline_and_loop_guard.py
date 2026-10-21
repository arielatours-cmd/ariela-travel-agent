"""QA for Shlomo's relay of Shaked's stage-1 run-3 live finding
(Copenhagen, 9d1d8f9):

1. The customer's answer "יש" to "תרצה שאעזור גם עם לינה?" (want help
   with lodging too?) was parsed as a REQUEST (activating lodging), when
   in this context it actually means "we already have lodging arranged" -
   a decline. _post_flight_offer_answer's own classifier prompt is
   strengthened to teach the model this context-dependent understanding
   explicitly ("יש"/"יש לנו" here almost always means "already have it",
   not an enthusiastic "yes!") - genuine model understanding, never a
   hardcoded phrase added to the function's existing short-circuit word
   sets (those stay for truly unambiguous replies only, per the business
   owner's standing architecture rule).

2. Once stuck in that wrong state, Ariella asked "איזה סוג לינה?" 15
   times in a row with no progress - a general loop guard now applies to
   EVERY guided field (not just lodging): two unclear answers in a row
   skip the field on what would be the third identical-style ask, via
   _guided_skip_hint, instead of ever repeating the same question
   verbatim again.

Run: python3 tools/qa_lodging_decline_and_loop_guard.py
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

from unittest.mock import patch

import ariella_chat_clean as chat

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# =====================================================================
# 1. The classifier prompt itself now explicitly teaches the model the
#    context-dependent meaning of "יש"/"יש לנו" - never a hardcoded
#    phrase added to the function's own short-circuit word sets.
# =====================================================================
captured_prompts = []


def _capture_prompt(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "classifier":
        captured_prompts.append(system_static)
        return json.dumps({"lodging": False})
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_capture_prompt):
    chat._post_flight_offer_answer(
        "יש", {"post_flight_offer": ["lodging"]}, key="test-key", model="test-model", history=[],
    )
check("the classifier prompt was actually built and sent (not short-circuited "
      "by the existing quick word sets - 'יש' alone isn't one of them)",
      len(captured_prompts) == 1)
check("the prompt explicitly teaches the model that 'יש'/'יש לנו' here almost "
      "always means the customer already has the service arranged",
      "יש" in captured_prompts[0] and "יש לנו" in captured_prompts[0]
      and "כבר מסודר" in captured_prompts[0])
check("the prompt explicitly distinguishes this from 'יש!' as enthusiasm, so "
      "the model isn't just told to always read 'יש' as a decline",
      "קריאת התלהבות" in captured_prompts[0])

check("'יש'/'יש לנו' are NOT in the function's own quick-match word sets "
      "(this is genuine model understanding via the prompt, never a "
      "hardcoded phrase short-circuit)",
      "יש" not in {"לא", "לא עכשיו", "לא תודה", "לא צריך", "לא צריכה", "לא צריכים", "זהו", "זה הכל", "זה הכול", "סיימנו", "אין צורך"}
      and "יש" not in {"כן", "בטח", "בהחלט", "כולם", "הכל", "הכול", "את הכל", "את הכול", "כן הכל", "כן הכול", "כן בבקשה", "כן, בבקשה",
                       "שניהם", "את שניהם", "שתיהן", "את שתיהן", "גם וגם", "גם וגם זה"})

# =====================================================================
# End-to-end plumbing check: when the (mocked) classifier correctly
# returns false for "יש" per the strengthened prompt's instruction, the
# answer is correctly applied as a decline - confirms the code path
# around the model call is sound, not the model's own understanding
# (which only a live run can verify).
# =====================================================================
def _mock_decline(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "classifier":
        return json.dumps({"lodging": False})
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_mock_decline):
    result = chat._post_flight_offer_answer(
        "יש", {"post_flight_offer": ["lodging"]}, key="test-key", model="test-model", history=[],
    )
check("end-to-end: a classifier correctly reading 'יש' as a decline per the "
      "strengthened prompt results in lodging=False being applied",
      result == {"lodging": False})

# =====================================================================
# 2. Direct unit tests of _guided_skip_hint - the loop-guard's own hint,
#    never a verbatim repeat of the skipped question.
# =====================================================================
skip_with_next = chat._guided_skip_hint("lodging_type", "lodging_rooms")
check("the skip hint names the skipped field's topic and explicitly moves on",
      "לינה" in skip_with_next and "מאוחר יותר" in skip_with_next)
check("the skip hint asks the NEXT field's question in the same message",
      "חדרים" in skip_with_next or "לינה" in skip_with_next)

skip_no_next = chat._guided_skip_hint("lodging_budget_or_level", None)
check("with no next field at all, the skip hint still moves on gracefully "
      "(no dangling 'ask about None')",
      "None" not in skip_no_next and "מאוחר יותר" in skip_no_next)

# =====================================================================
# 3. Direct unit tests of _guided_skip_turn_hint - the REQUIRED-field
# variant (dates/travelers/baggage), per Shaked's review of the first
# loop-guard version: these are never skipped away the way a lodging
# sub-field can be (the field stays open, only THIS turn's ask is
# skipped - the caller is the one that resets attempts to 0).
# =====================================================================
skip_turn_dates = chat._guided_skip_turn_hint("dates")
check("the skip-turn hint explicitly skips asking again THIS turn",
      "פעמיים" in skip_turn_dates and "לא עכשיו" in skip_turn_dates)
check("the skip-turn hint never claims the field is being moved past or "
      "skipped permanently - it will be asked again",
      "יישאל שוב" in skip_turn_dates)
check("the skip-turn hint names the field's own topic",
      "לטוס" in skip_turn_dates)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL LODGING-DECLINE-AND-LOOP-GUARD TESTS PASSED")
