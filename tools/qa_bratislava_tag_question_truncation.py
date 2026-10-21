"""QA for Shaked's direct stage-1 run-4 report, Bratislava finding #4:

After the customer answered "אני מסתדרת עם טרולי, לבנים צריך מזוודה" (I'm
fine with a trolley, the kids need a suitcase), the reply came back as
'\\n\\nמה התקציב שלכם לאדם לטיסה?' - the first part (the acknowledgment of
the baggage answer) was gone, leaving only a leading blank line before the
budget question.

Root cause, found by direct reproduction: Tinkerbell's raw reply phrased
the acknowledgment as a Hebrew TAG question ("...תמיד אפשר להוסיף מזוודה
בבטן המטוס בהמשך, נכון?" - "...right?"), structurally a statement with a
trailing confirmation tag, not a real open question. _enforce_one_option_
question counts ANY sentence ending in "?" as a question with no such
distinction - with the tag sentence AND the real budget question both
counted, it correctly detected "more than one question" and rebuilt the
reply around its own freshly-computed single fixed question (identical
text to what was already there) - but in doing so dropped BOTH original
question-marked spans, including the acknowledgment's own content, leaving
only the blank-line span between them (preserved, since only
term=="?" spans are removed) followed by the re-appended fixed question.

Fixed: _CONFIRMATION_TAG_QUESTION_RE recognizes the structural pattern of
a Hebrew tag question (a comma directly before נכון/לא/כן, then only "?" to
the end of the sentence) and excludes it from question_idx - exactly the
same kind of FORMAT-based signal this function already uses for " או "/
_BUNDLED_AND_QUESTION_RE, never a meaning/model judgment call.

Run: python3 tools/qa_bratislava_tag_question_truncation.py
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


_FLIGHTS_STATE_BUDGET_GAP = {
    "active_session": "flights",
    "trip_type": "standard",
    "requested_services": ["flights"],
    "service_decisions": {"flights": {"wanted": True}},
    "destination": {"places": ["ברטיסלבה"], "mode": "specific", "status": "known"},
    "destination_airports": ["BTS"],
    "departure_airport": "TLV",
    "travelers": {"adults": 2, "children": 1, "child_ages": [10]},
    "dates": {"departure": "2027-03-05", "return": "2027-03-10", "needs_confirmation": False},
    "flight": {"baggage": ["carry_on_only", "checked_bag"]},
}

# =====================================================================
# Direct unit tests of _CONFIRMATION_TAG_QUESTION_RE.
# =====================================================================
check("'..., נכון?' matches the tag-question pattern",
      bool(chat._CONFIRMATION_TAG_QUESTION_RE.search("תמיד אפשר להוסיף מזוודה, נכון?")))
check("'..., לא?' matches the tag-question pattern",
      bool(chat._CONFIRMATION_TAG_QUESTION_RE.search("אז סגרנו את הכבודה, לא?")))
check("'..., כן?' matches the tag-question pattern",
      bool(chat._CONFIRMATION_TAG_QUESTION_RE.search("זה מספיק, כן?")))
check("a genuine open question ('מה התקציב שלכם?') does NOT match - no "
      "comma+tag-word structure at all",
      not chat._CONFIRMATION_TAG_QUESTION_RE.search("מה התקציב שלכם לאדם לטיסה?"))
check("'נכון?' with NO comma before it does not match - the comma is "
      "part of the required structural shape",
      not chat._CONFIRMATION_TAG_QUESTION_RE.search("האם זה נכון?"))

# =====================================================================
# End-to-end reproduction: Shaked's exact Bratislava shape. The
# acknowledgment (phrased as a tag question) must survive intact, and the
# real budget question (already correct) stays exactly as Tinkerbell wrote
# it - no truncation to a bare leading blank line.
# =====================================================================
_bratislava_raw = (
    "תמיד אפשר להוסיף מזוודה בבטן המטוס בהמשך, נכון?"
    "\n\nמה התקציב שלכם לאדם לטיסה?"
)
_fixed_reply = chat._enforce_one_option_question(_bratislava_raw, dict(_FLIGHTS_STATE_BUDGET_GAP))
check("the exact Bratislava shape (tag-question ack + real budget "
      "question) is returned completely unchanged - the acknowledgment "
      "is never dropped",
      _fixed_reply == _bratislava_raw)
check("specifically: the reply no longer starts with a bare blank line "
      "and nothing else before the real question (the live customer-"
      "visible symptom)",
      not _fixed_reply.startswith("\n\n"))
check("the acknowledgment's own content ('תמיד אפשר להוסיף מזוודה') "
      "is present in the final reply",
      "תמיד אפשר להוסיף מזוודה" in _fixed_reply)

# "לא?" and "כן?" tag variants, same shape.
for _tag_word, _label in (("לא", "לא?"), ("כן", "כן?")):
    _raw = f"אז סגרנו את הכבודה, {_tag_word}?\n\nמה התקציב שלכם לאדם לטיסה?"
    _result = chat._enforce_one_option_question(_raw, dict(_FLIGHTS_STATE_BUDGET_GAP))
    check(f"the '{_label}' tag variant also survives intact, same shape",
          _result == _raw)

# =====================================================================
# Regression: the ORIGINAL purpose of this function - two genuinely
# separate, non-tag question sentences - must still be collapsed into the
# single state-driven question exactly as before this fix.
# =====================================================================
_two_real_questions = "רוצה לדעת גם אם יש העדפת כיסא?\n\nמה התקציב שלכם לאדם לטיסה?"
_collapsed = chat._enforce_one_option_question(_two_real_questions, dict(_FLIGHTS_STATE_BUDGET_GAP))
check("regression: two genuinely separate real questions are still "
      "correctly collapsed to the one real state-driven question - the "
      "one-question-per-message rule itself is untouched by this fix",
      "העדפת כיסא" not in _collapsed and "מה התקציב שלכם לאדם לטיסה?" in _collapsed)

# Regression: a reply that is ONLY a tag question, with no real question
# in it at all, is left completely untouched (nothing to enforce, no real
# question sentence exists).
_only_tag = "זה בסדר, נכון?"
check("regression: a reply that is only a tag question (no real question "
      "sentence at all) is left completely untouched",
      chat._enforce_one_option_question(_only_tag, dict(_FLIGHTS_STATE_BUDGET_GAP)) == _only_tag)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL BRATISLAVA-TAG-QUESTION-TRUNCATION TESTS PASSED")
