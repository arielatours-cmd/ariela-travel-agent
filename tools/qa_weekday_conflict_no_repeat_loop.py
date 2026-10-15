"""QA for a live WhatsApp loop bug Carmit found herself (15.10.2026, 20:24-
20:26 Israel time, Meta's test number - screenshot: ceo/evidence/2026-10-15-
whatsapp-loop-thu-sat.jpg): a stale "חמישי עד שבת" phrase (from an unrelated
earlier lodging/route instruction, not a statement about the trip's own
departure/return days) made _weekday_date_conflict ask "19.09.2027 יוצא ביום
ראשון, וביקשת חמישי עד שבת... התכוונת ליום חמישי 16.09.2027 או 23.09.2027?".
She replied with the exact same dates she'd already given ("19.9 עד 30.9"),
and Ariella asked the IDENTICAL question again, verbatim - a loop.

Root cause of the loop specifically (separate from whatever produced the
stale "חמישי עד שבת" match in the first place, still open pending the exact
verbatim source message): repeating the same answer to a clarification
question is the customer's confirmation, not new information to re-question.
_weekday_date_conflict had no memory of having just asked this.

Two independent fixes:
1. _already_asked_weekday_conflict(history, conflict_text): the chat-clean
   route now checks whether the most recent assistant turn already asked
   the identical date+weekday clarification (matched on the clause up to
   "וביקשת", which already pins the specific date/weekday pair) - if so, it
   skips re-asking and lets normal processing continue instead.
2. _weekday_pair_conflict's history scan: reproducing the live bug showed
   the existing lodging-context cue-word list (_WEEKDAY_PAIR_LODGING_CONTEXT
   _CUES) does NOT catch every real phrasing of a lodging/route aside - e.g.
   "נשאר שם מחמישי עד שבת" (no literal cue word) still false-triggers.
   Added a structural check instead of another word to chase: a trip's own
   departure/return weekday range is only ever meaningful once pinned to a
   real calendar date, so a bare weekday-pair with NO date anywhere in that
   same historical message is now always rejected, regardless of wording.

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


# --- 1a. Reproducing the live bug's stale-lodging-note trigger with the
#         SAME wording the fix comment already documented (cue-word
#         list catches this one) - must stay suppressed ---
history_cue_word_case = [
    {"role": "user", "content": "כל 2 ימים לישון באותו מקום רק בסוף שבוע חמישי עד שבת לישון באותו מקום"},
]
check("a lodging aside matching an existing cue word is still suppressed",
      chat._weekday_date_conflict("19.9 עד 30.9", history_cue_word_case) is None)

# --- 1b. The real gap this fix closes: the SAME kind of lodging/route aside,
#         worded WITHOUT any literal cue word and with no date nearby - the
#         structural "needs a date in the same message" check must catch
#         what the word list alone cannot ---
history_no_cue_word = [
    {"role": "user", "content": "נשאר שם מחמישי עד שבת באזור הזה"},
]
check("a lodging/route aside with no cue word AND no date is also suppressed (structural check)",
      chat._weekday_date_conflict("19.9 עד 30.9", history_no_cue_word) is None)

# --- 1c. A genuine weekday-pair anchored to a real date must still trigger
#         the clarification - the fix must not over-suppress ---
history_real_weekday_claim = [
    {"role": "user", "content": "רוצים לטוס מיום חמישי עד יום שבת, ב-16.9 בערך"},
]
conflict = chat._weekday_date_conflict("19.9 עד 30.9", history_real_weekday_claim)
check("a weekday-pair anchored to a real date in the same message still triggers",
      bool(conflict) and "יוצא ביום ראשון" in conflict)

# --- 2. The loop itself: once Ariella has already asked this exact
#        clarification and the customer repeats the same dates, she must
#        NOT ask it again ---
history_already_asked = history_real_weekday_claim + [
    {"role": "assistant", "content": conflict},
]
already_asked = chat._already_asked_weekday_conflict(history_already_asked, conflict)
check("recognizes the identical question was already asked in the last assistant turn",
      already_asked is True)

# --- 3. Regression guard: a GENUINELY new conflict (different date/weekday
#        pair never asked before) must still be asked normally ---
fresh_history = [
    {"role": "assistant", "content": "מתי תרצו לטוס?"},
]
check("a conflict never asked before is not suppressed",
      chat._already_asked_weekday_conflict(fresh_history, conflict) is False)

# --- 4. Regression guard: an empty/no history never crashes and is never
#        treated as 'already asked' ---
check("no history at all -> never treated as already-asked",
      chat._already_asked_weekday_conflict([], conflict) is False)
check("None history -> never treated as already-asked",
      chat._already_asked_weekday_conflict(None, conflict) is False)

# --- 5. Regression guard: only the MOST RECENT assistant turn counts - an
#        older identical question from further back must not suppress a
#        fresh new ask if the most recent assistant turn was unrelated ---
history_old_then_unrelated = [
    {"role": "assistant", "content": conflict},
    {"role": "user", "content": "19.9 עד 30.9"},
    {"role": "assistant", "content": "כמה נוסעים אתם?"},
]
check("an unrelated, more recent assistant turn does not suppress a fresh ask",
      chat._already_asked_weekday_conflict(history_old_then_unrelated, conflict) is False)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL WEEKDAY-CONFLICT-NO-REPEAT-LOOP TESTS PASSED")
