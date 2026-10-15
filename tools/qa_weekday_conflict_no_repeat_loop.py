"""QA for a live WhatsApp loop bug Carmit found herself (15.10.2026, 20:24-
20:26 Israel time, Meta's test number - screenshot: ceo/evidence/2026-10-15-
whatsapp-loop-thu-sat.jpg): a stale "חמישי עד שבת" phrase (from an unrelated
earlier lodging/route instruction, from a PREVIOUS, already-approved trip -
not a statement about the current trip's own departure/return days) made
_weekday_date_conflict ask "19.09.2027 יוצא ביום ראשון, וביקשת חמישי עד
שבת... התכוונת ליום חמישי 16.09.2027 או 23.09.2027?". She replied with the
exact same dates she'd already given ("19.9 עד 30.9"), and Ariella asked the
IDENTICAL question again, verbatim - a loop.

Shaked reproduced this offline and traced the root cause further than the
first pass here did (qa/cases.json on the shaked branch, commit d4b88ca):
_weekday_pair_conflict's backward history scan had no concept of "that was
a different, already-submitted request" - it kept scanning straight through
an approved/closed previous trip. Per Shlomo/the business owner: the fix is
trip-scoping, not another word added to the lodging-context cue list
(_WEEKDAY_PAIR_LODGING_CONTEXT_CUES) - a weekday pair from a trip the
customer already finalized must never leak into a new one, regardless of
its exact wording.

Two fixes, both now live inside _weekday_date_conflict itself (not only the
chat-clean route, so the function's own return value is correct on its
own - this is exactly what Shaked's qa/cases.json cases call and check):

1. _weekday_pair_conflict's backward scan now stops the moment it reaches a
   bare "מאשר"/"מאשרת" user reply - the one reserved word the whole system
   already treats as a request's real activation/finalization
   (_approval_trigger matches the identical bare word). Everything further
   back belongs to that earlier, closed request.
2. _already_asked_weekday_conflict(history, conflict_text): if the most
   recent assistant turn already asked the identical date+weekday
   clarification (matched on the clause up to "וביקשת", which already pins
   the specific date/weekday pair), _weekday_date_conflict returns None
   instead of handing back the same question again - a repeated identical
   answer IS the confirmation, not new information to re-question.

Includes Shaked's exact three qa/cases.json cases (weekday-pair-repeat-
same-dates-closes-question, weekday-pair-from-approved-previous-trip-
ignored, weekday-pair-real-conflict-still-asked) so this file and the
offline suite never drift apart on the same bug.

Run: python3 tools/qa_weekday_conflict_no_repeat_loop.py
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


# --- Shaked's exact 3 cases (qa/cases.json, shaked branch, commit d4b88ca) ---

# 1. weekday-pair-repeat-same-dates-closes-question
h1 = [
    {"role": "user", "content": "בסוף שבוע חמישי עד שבת רוצה להיות בעיר אחת"},
    {"role": "user", "content": "זוג +2 טסים בספטמבר 19.9 עד 30.9 12 יום"},
    {"role": "assistant", "content": ("רק לוודא — 19.09.2027 יוצא ביום ראשון, וביקשת חמישי עד שבת. "
                                        "התכוונת ליום חמישי 16.09.2027 או ליום חמישי 23.09.2027? "
                                        "או שנשנה את ימי הנסיעה?")},
]
check("weekday-pair-repeat-same-dates-closes-question: repeating the same dates closes the question",
      not chat._weekday_date_conflict("19.9 עד 30.9", h1))

# 2. weekday-pair-from-approved-previous-trip-ignored
h2 = [
    {"role": "user", "content": "בסוף שבוע חמישי עד שבת רוצה להיות בעיר אחת"},
    {"role": "assistant", "content": "אם כל הפרטים נכונים, כתבי מאשרת."},
    {"role": "user", "content": "מאשרת"},
    {"role": "assistant", "content": "הבקשה אושרה ואני יוצאת לסריקת טיסות. אעדכן אותך כשהתוצאות יהיו מוכנות."},
]
check("weekday-pair-from-approved-previous-trip-ignored: a weekday pair from a closed previous trip never leaks in",
      not chat._weekday_date_conflict("זוג +2 טסים בספטמבר 19.9 עד 30.9 12 יום", h2))

# 3. weekday-pair-real-conflict-still-asked
h3 = [{"role": "user", "content": "אני רוצה לטוס מחמישי עד שבת"}]
check("weekday-pair-real-conflict-still-asked: a genuine conflict is still caught",
      bool(chat._weekday_date_conflict("19.9 עד 30.9", h3)))


# --- Further coverage of the two fixes individually ---

# --- 4. A genuine weekday-pair conflict, matching the live screenshot's
#        exact wording ("רוצים לטוס" - travel intent, not a lodging aside) ---
history_real_weekday_claim = [
    {"role": "user", "content": "רוצים לטוס מיום חמישי עד יום שבת, ב-16.9 בערך"},
]
conflict = chat._weekday_date_conflict("19.9 עד 30.9", history_real_weekday_claim)
check("a genuine weekday-pair claim produces a conflict to ask about",
      bool(conflict) and "יוצא ביום ראשון" in conflict)

# --- 5. The loop itself, as a direct call to the helper: once Ariella has
#        already asked this exact clarification and the customer repeats
#        the same dates, she must NOT ask it again ---
history_already_asked = history_real_weekday_claim + [
    {"role": "assistant", "content": conflict},
]
already_asked = chat._already_asked_weekday_conflict(history_already_asked, conflict)
check("recognizes the identical question was already asked in the last assistant turn",
      already_asked is True)

# --- 6. Regression guard: a GENUINELY new conflict (different date/weekday
#        pair never asked before) must still be asked normally ---
fresh_history = [
    {"role": "assistant", "content": "מתי תרצו לטוס?"},
]
check("a conflict never asked before is not suppressed",
      chat._already_asked_weekday_conflict(fresh_history, conflict) is False)

# --- 7. Regression guard: an empty/no history never crashes and is never
#        treated as 'already asked' ---
check("no history at all -> never treated as already-asked",
      chat._already_asked_weekday_conflict([], conflict) is False)
check("None history -> never treated as already-asked",
      chat._already_asked_weekday_conflict(None, conflict) is False)

# --- 8. Regression guard: only the MOST RECENT assistant turn counts - an
#        older identical question from further back must not suppress a
#        fresh new ask if the most recent assistant turn was unrelated ---
history_old_then_unrelated = [
    {"role": "assistant", "content": conflict},
    {"role": "user", "content": "19.9 עד 30.9"},
    {"role": "assistant", "content": "כמה נוסעים אתם?"},
]
check("an unrelated, more recent assistant turn does not suppress a fresh ask",
      chat._already_asked_weekday_conflict(history_old_then_unrelated, conflict) is False)

# --- 9. Regression guard: "מאשר" (the masculine form) stops the scan too,
#        not only "מאשרת" ---
h9 = [
    {"role": "user", "content": "רוצה להישאר באזור אחד בסופי שבוע חמישי עד שבת"},
    {"role": "assistant", "content": "אם כל הפרטים נכונים, כתוב מאשר."},
    {"role": "user", "content": "מאשר"},
    {"role": "assistant", "content": "הבקשה אושרה."},
]
check("the masculine 'מאשר' confirmation also stops the backward scan",
      not chat._weekday_date_conflict("19.9 עד 30.9", h9))

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL WEEKDAY-CONFLICT-NO-REPEAT-LOOP TESTS PASSED")
