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

Fixed (round 1): _CONFIRMATION_TAG_QUESTION_RE recognizes the structural
pattern of a Hebrew tag question (a comma directly before נכון/לא/כן, then
only "?" to the end of the sentence) and excludes it from question_idx -
exactly the same kind of FORMAT-based signal this function already uses
for " או "/_BUNDLED_AND_QUESTION_RE, never a meaning/model judgment call.

Shaked did not approve round 1: a word-list regex can never cover every
Hebrew tag ending ("בסדר?"/"מתאים?"/"טוב?"/...), and her own counter-example
("…לכולם, בסדר?\n\nמה התקציב…?") proved it - "בסדר?" isn't covered by
_CONFIRMATION_TAG_QUESTION_RE at all, and in the "no fixed replacement"
branch (no gap, no pending offer), the code kept the FIRST question
sentence and dropped the rest - exactly backwards, since a short
confirmation tag is routinely first and the real, conversation-advancing
question comes last.

Fixed (round 2, structural rather than lexical): that branch now keeps
the LAST question sentence and drops every one before it - the one that
actually moves the conversation forward is overwhelmingly the final one,
tag or not, so no finite word list is needed at all. _append_fixed_
question and this branch's own output also strip only the leading/
trailing edges of the final message (never anything internal), so a bare
"\\n"-span left dangling by a dropped leading sentence never again starts
a reply with a blank line and nothing before it - the live symptom.
_CONFIRMATION_TAG_QUESTION_RE is kept as a complementary, lower-priority
signal for the (different) branch where a real fixed replacement DOES
exist - no longer the only defense.

Shaked did not approve round 2 either: "always keep the last question" has
the opposite live failure - "מה התקציב שלכם לאדם לטיסה? ונוח לכם בבוקר?"
kept "ונוח לכם בבוקר?" (a grammatical CONTINUATION of the budget question,
not an independent one) and dropped the real missing-gap question.

Fixed (round 3, her own exact decision order): a question sentence
starting with the bound "ו" prefix or the standalone word "או" is a
continuation of the question immediately before it - keep that PRECEDING
question instead. In every other case, keep the last question (round 2's
rule, unchanged). _QUESTION_CONTINUATION_RE recognizes only this narrow,
unambiguous structural pattern - her own stated safety rule (never guess
further than this) is why nothing more elaborate was added.

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

# =====================================================================
# Round 2 (Shaked's rejection of round 1): her own counter-example, where
# the "no fixed replacement" branch (no gap, no pending offer domain) used
# to keep the FIRST question and drop the rest - exactly backwards, since
# a short confirmation tag ("בסדר?"/"מתאים?"/"טוב?") is routinely the
# FIRST question sentence and the real, conversation-advancing question
# comes LAST. "בסדר?" has no comma+tag-word structure at all, so
# _CONFIRMATION_TAG_QUESTION_RE never catches it - the fix had to be
# structural (keep the LAST question), not another word added to a list.
# =====================================================================
_NO_PENDING_OFFER_STATE = {
    "session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
}
check("sanity check for this section's own premise: no pending offer "
      "domain exists for this state, so 'fixed' will be None and the "
      "'no fixed replacement' branch is the one under test",
      chat._pending_offer_domain(_NO_PENDING_OFFER_STATE) is None)

_shaked_counterexample = "מעולה, שמרתי את זה לכולם, בסדר?\n\nמה התקציב שלכם לאדם לטיסה?"
_result = chat._enforce_one_option_question(_shaked_counterexample, dict(_NO_PENDING_OFFER_STATE))
check("Shaked's exact counter-example ('…לכולם, בסדר?\\n\\nמה התקציב…?'): "
      "the REAL, conversation-advancing question survives - 'בסדר?' is "
      "dropped, not the budget question",
      _result == "מה התקציב שלכם לאדם לטיסה?")
check("no leading blank line survives either, even though 'בסדר?' isn't "
      "a recognized tag pattern at all",
      not _result.startswith("\n") and not _result.startswith(" "))

# "מתאים?" and "טוב?" - two more common Hebrew tag endings that
# _CONFIRMATION_TAG_QUESTION_RE was never meant to cover exhaustively;
# the structural last-question fix handles them the same way regardless.
for _tag_ending in ("מתאים?", "טוב?", "אחלה?"):
    _raw = f"מעולה, שמרתי את זה לכולם, {_tag_ending}\n\nמה התקציב שלכם לאדם לטיסה?"
    _res = chat._enforce_one_option_question(_raw, dict(_NO_PENDING_OFFER_STATE))
    check(f"tag ending '{_tag_ending}' (not covered by any fixed word list) "
          "still keeps the real question, not the tag",
          _res == "מה התקציב שלכם לאדם לטיסה?")

# Regression: with only ONE question sentence and no fixed replacement,
# the reply is still returned completely unchanged (the Paris rule: never
# drop the only question there is).
_single_question_state = dict(_NO_PENDING_OFFER_STATE)
_single = "מעולה, שמרתי את זה. מה התקציב שלכם לאדם לטיסה?"
check("regression: a single real question with no fixed replacement is "
      "still never dropped (the Paris rule)",
      chat._enforce_one_option_question(_single, _single_question_state) == _single)

# =====================================================================
# Round 3 (Shaked's second rejection): her own exact counter-example - the
# trailing question is a grammatical CONTINUATION of the one before it
# (starts with the bound "ו" prefix), not an independent second question.
# "Always keep the last" (round 2's rule alone) drops the wrong one here.
# =====================================================================
check("'ונוח לכם בבוקר?' (bound ו-prefix) matches the continuation pattern",
      bool(chat._QUESTION_CONTINUATION_RE.match("ונוח לכם בבוקר?")))
check("'או שתעדיפו...?' (standalone או, followed by whitespace) matches too",
      bool(chat._QUESTION_CONTINUATION_RE.match("או שתעדיפו בערב?")))
check("a genuine independent question ('מה התקציב...?') does NOT match - "
      "no leading ו/או at all",
      not chat._QUESTION_CONTINUATION_RE.match("מה התקציב שלכם לאדם לטיסה?"))
check("a word that merely CONTAINS 'או' without being the standalone word "
      "('אולי') does not match - only 'או' followed by whitespace/end does",
      not chat._QUESTION_CONTINUATION_RE.match("אולי מתאים לכם בבוקר?"))

_shaked_round3_example = "מה התקציב שלכם לאדם לטיסה? ונוח לכם בבוקר?"
_result3 = chat._enforce_one_option_question(_shaked_round3_example, dict(_NO_PENDING_OFFER_STATE))
check("Shaked's round-3 counter-example: the REAL missing-gap question "
      "('מה התקציב...?') survives - 'ונוח לכם בבוקר?' is recognized as its "
      "continuation and dropped, not the other way around",
      _result3 == "מה התקציב שלכם לאדם לטיסה?")

# The round-2 fix (plain "keep last") must still apply whenever the last
# question is NOT a continuation - this is round 2's own counter-example,
# restated to confirm round 3 didn't regress it.
_result_round2_still_ok = chat._enforce_one_option_question(
    "מעולה, שמרתי את זה לכולם, בסדר?\n\nמה התקציב שלכם לאדם לטיסה?",
    dict(_NO_PENDING_OFFER_STATE),
)
check("regression: round 2's own counter-example (no continuation "
      "involved, plain tag-first/real-question-last) still resolves "
      "correctly after adding the continuation check",
      _result_round2_still_ok == "מה התקציב שלכם לאדם לטיסה?")

# A chain of 3 questions where only the very last is a continuation of the
# middle one - the middle one (its true parent) is kept, not the first.
_three_question_chain = "מעולה, נרשם. חשוב לכם שהטיסה תהיה ישירה? איזו כבודה תרצו לקחת? ומתי תרצו לטוס?"
check("a 3-question chain where only the LAST is a continuation (of the "
      "MIDDLE one): the middle question is kept, the first (unrelated) "
      "and last (its own continuation) are both dropped",
      chat._enforce_one_option_question(_three_question_chain, dict(_NO_PENDING_OFFER_STATE))
      == "מעולה, נרשם. איזו כבודה תרצו לקחת?")

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL BRATISLAVA-TAG-QUESTION-TRUNCATION TESTS PASSED")
