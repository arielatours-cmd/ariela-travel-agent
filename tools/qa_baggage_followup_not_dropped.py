"""QA for Shlomo's relay of Shaked's live stage-1 run-1 finding (20.10.2026,
b71506d, 1/5 - qa/reports/2026-10-20-stage1-live-run1.md on the shaked
branch), priority fix #3 of four blocking stage-1:

s1a1: "טרולי לכל אחד", ובתשובה "יש לך הגבלת תקציב...?" בלי "אפשר להוסיף
מזוודה". s1a3: "רק תיק יד", ובתשובה "מה התקציב...?" בלי "אפשר להוסיף טרולי
או מזוודה". בשני המקרים הכבודה הייתה השאלה הנוכחית.

Investigation: budget_per_person is NOT a GUIDED_EXTRACTION_STEPS field
(guided_order only covers dates/travelers/baggage/the lodging subfields),
so after baggage is answered, _handle_guided_extraction_turn's own
"next_field" search finds nothing to combine the note with - the
dynamic_hint handed to Tinkerbell is JUST _baggage_followup_hint's note,
standing completely alone. The note already told her to move to "the next
topic" herself in the same message, but handed only that bare statement
against TINKERBELL_SYSTEM's own strict one-question-per-message rule, she
may have played safe and kept only the next question (budget, derived from
her own separate missing-fields logic), dropping the note.

This is a pure prompt-adherence fix, not a logic bug - the note's wording
now states explicitly that adding it before the next question is still one
compliant message (matching the rule's own documented precedent of a
statement plus one question together), and explicitly forbids dropping it
just to keep the message down to one question. Also hardens the OTHER
combination site (when the next GUIDED field - e.g. travelers/lodging -
does get a companion hint) with the same explicit numbered reassurance.

Run: python3 tools/qa_baggage_followup_not_dropped.py
"""
import os
import sys
import json
from unittest.mock import patch

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
# The standalone note (the actual shape that reaches Tinkerbell in s1a1/
# s1a3, since budget has no guided hint to combine with) now explicitly
# forbids dropping it, and reassures it's still one compliant message.
# =====================================================================
_note_carry_on = chat._baggage_followup_hint(["carry_on_only"])
check("the standalone note explicitly forbids dropping it just to keep "
      "the message to one question",
      "אסור להשמיט אותו רק כדי להישאר עם שאלה אחת" in _note_carry_on)
check("the standalone note explicitly states this is still one compliant "
      "message with one question, not two",
      "זו עדיין הודעה אחת תקינה עם שאלה אחת בלבד" in _note_carry_on)
check("the standalone note explicitly tells her to continue to the next "
      "genuinely relevant question (e.g. budget) in the same message",
      "המשיכי לשאלה הבאה שבאמת רלוונטית כרגע" in _note_carry_on
      and "תקציב" in _note_carry_on)
check("the standalone note still mentions a suitcase can be added later "
      "(carry_on_only chosen)",
      "שאפשר תמיד להוסיף מזוודה בבטן המטוס" in _note_carry_on)

_note_personal_item = chat._baggage_followup_hint(["personal_item"])
check("personal_item alone still mentions BOTH a trolley and a suitcase "
      "can be added later",
      "טרולי" in _note_personal_item and "מזוודה" in _note_personal_item)

# 22.10 (business owner, replacing a rejected after-the-fact filter): the
# checked bag still gets NO "can add" note for the customer - the hint is
# now an explicit instruction to the model NOT to write one (was None).
check("checked_bag (top tier) still needs no note at all - explicit 'add nothing' instruction instead of None",
      "אל תוסיפי שום משפט על הוספת כבודה נוספת" in (chat._baggage_followup_hint(["checked_bag"]) or "")
      and "שאפשר תמיד להוסיף" not in (chat._baggage_followup_hint(["checked_bag"]) or ""))

# =====================================================================
# End-to-end simulation of s1a1/s1a3's exact shape: baggage is the
# current guided question, budget_per_person is NOT a guided field (no
# companion next_hint exists) - confirms the dynamic_hint Tinkerbell
# actually receives is this same explicit, hardened note.
# =====================================================================
def _fake_post_claude(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "guided_extract":
        return json.dumps({
            "status": "answered", "no_baggage": False, "mixed_per_passenger": False,
            "items": [{"type": "carry_on_only", "count": None, "size": None}],
            "confidence": "high", "also_mentioned": {}, "correction": None,
        })
    return "{}"


trip_state = {
    "guided": {"current_question": "baggage", "attempts": 0, "answered": []},
    "flight": {"baggage": []},
    "budget_per_person": {"status": "unknown"},
    "destination": {"places": ["ורשה"]},
    "requested_services": ["flights"],
}
trip_update = dict(trip_state)
guided_steps = {"baggage"}  # budget_per_person is never a guided step

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    result = chat._handle_guided_extraction_turn("key", "model", "טרולי לכל אחד", [], trip_state, trip_update, guided_steps)

hint = result.get("dynamic_hint") or ""
check("s1a1's exact shape (baggage answered, budget next but not a guided "
      "field) -> the dynamic_hint Tinkerbell receives still carries the "
      "hardened 'do not drop this' instruction",
      "אסור להשמיט אותו" in hint and "שאפשר תמיד להוסיף מזוודה" in hint)

# =====================================================================
# Regression: when the NEXT field genuinely IS a guided field (e.g.
# travelers, still open), the combined hint explicitly numbers both
# parts and reassures this still counts as one question.
# =====================================================================
def _fake_post_claude_with_next_guided(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "guided_extract":
        return json.dumps({
            "status": "answered", "no_baggage": False, "mixed_per_passenger": False,
            "items": [{"type": "personal_item", "count": None, "size": None}],
            "confidence": "high", "also_mentioned": {}, "correction": None,
        })
    return "{}"


trip_state2 = {
    "guided": {"current_question": "baggage", "attempts": 0, "answered": ["dates"]},
    "flight": {"baggage": []},
    "travelers": {"adults": None},
    "destination": {"places": ["ורשה"]},
    "requested_services": ["flights"],
}
trip_update2 = dict(trip_state2)
guided_steps2 = {"dates", "travelers", "baggage"}

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_with_next_guided):
    result2 = chat._handle_guided_extraction_turn("key", "model", "רק תיק יד", [], trip_state2, trip_update2, guided_steps2)

hint2 = result2.get("dynamic_hint") or ""
check("when the next field IS a guided field (travelers), the combined "
      "hint numbers both parts explicitly as (1) and (2)",
      "(1)" in hint2 and "(2)" in hint2)
check("the combined hint reassures this still counts as one question, "
      "not a rule violation",
      "זה עדיין נחשב הודעה אחת" in hint2)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL BAGGAGE-FOLLOWUP-NOT-DROPPED TESTS PASSED")
