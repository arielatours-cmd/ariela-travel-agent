"""QA for Shlomo's 5l follow-up list (23.10.2026, relayed after Shaked's
qa/reports/2026-10-23-dryrun5l.md, SHA 2084d74 on branch `shaked`, 4/4 pass):
three small items queued for a follow-up PR before round 13.

(a) J7 ("וינה -> פראד"): PRG is saved to trip_update in the SAME turn
(destination_change with verified=true), but Tinkerbell's reply hedged -
"ברור, פראג זה יעד נהדר לינואר. רק רוצה לוודא שהעדכון ליעד אכן נקלט אצלי
לפני שנמשיך - בינתיים אני ממשיכה לבדוק את זה." - describing a save that
already happened as still in progress. Root cause (Shaked's own
hypothesis): TINKERBELL_SYSTEM's instruction never to confirm an unsaved
destination change is correct, but the raw state JSON dump alone gives no
EXPLICIT signal that THIS turn is when it was saved, so the model hedges
defensively. Fixed: _run_destination_recognition's own already-settled-
correction branch (unresolved_places is None) sets a one-turn marker,
_destination_change_confirmed_fact, surfaced via the new
_destination_change_confirmed_fact_text(state) as an explicit FACT
sentence in system_dynamic - the same "state, not model inference" pattern
used by every other deterministic fact in this file, and the same outcome
J6's silent path already gets for free since it composes its own reply
text directly instead of leaving confirmation to Tinkerbell's own
judgment. Popped at the top of _resolve_destination_by_meaning so it never
survives into a second turn's trip_state.

(b) Narrow the _enforce_one_option_question destination exemption so only
the "או" check on the destination sentence itself is exempted, not "one
question per turn" generally - covered by
tools/qa_dryrun5k_enforce_one_option_destination_question.py's own
follow-up checks (added same round), not repeated here.

(c) Two small recurring model wording glitches, same _fix_known_typos
philosophy as the existing נתב"ג/יעדיפות fixes: J1's "ללעיר" (doubled ל
before "עיר") and J0's "רק שרוצה לוודא" (a dropped אני).

Run: python3 tools/qa_dryrun5l_j7_fact_and_typos.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import ariella_chat_clean as chat

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


# =====================================================================
# (a) _destination_change_confirmed_fact_text itself
# =====================================================================
check("(a) no marker in state -> no fact text at all (never a bare empty "
      "instruction block)",
      chat._destination_change_confirmed_fact_text({}) == "")

_fact_text = chat._destination_change_confirmed_fact_text(
    {"_destination_change_confirmed_fact": "פראג"})
check("(a) marker present -> an explicit, unambiguous confirmed-fact "
      "sentence naming the new destination",
      "פראג" in _fact_text and "נשמר" in _fact_text)
check("(a) the fact text explicitly forbids the exact hedging language seen "
      "live (never telling Tinkerbell to re-verify a save that already "
      "happened)",
      "ספק" in _fact_text or "לעולם אל" in _fact_text)

# =====================================================================
# (a) the one-turn marker is popped by _resolve_destination_by_meaning
# itself on a LATER turn where nothing changed this time - it must never
# survive into a second turn's trip_state as a stale, no-longer-true fact.
# =====================================================================
STALE_STATE = {
    "destination_airports": ["PRG"],
    "destination": {"places": ["פראג"], "mode": "specific", "status": "known"},
    "_destination_change_confirmed_fact": "פראג",
}
_stale_result = chat._resolve_destination_by_meaning(
    STALE_STATE, dict(STALE_STATE), None, "מה לגבי כבודה?", [])
check("(a) regression: a stale marker from a PRIOR turn's trip_state is "
      "popped, not carried forward as if this turn just saved it again",
      "_destination_change_confirmed_fact" not in _stale_result)

# =====================================================================
# (c) the two small typo fixes, same mechanism/philosophy as the existing
# נתב"ג and יעדיפות fixes already in _fix_known_typos.
# =====================================================================
check('(c) J1 FIX: doubled ל before "עיר" ("ללעיר") is corrected to "לעיר"',
      chat._fix_known_typos("אתה מתכוון ללעיר בצרפת, או שבעצם התכוונת ליוון כיעד?")
      == "אתה מתכוון לעיר בצרפת, או שבעצם התכוונת ליוון כיעד?")
check('(c) J0 FIX: the dropped-אני glitch ("רק שרוצה לוודא") is corrected to '
      '"רק רוצה לוודא"',
      chat._fix_known_typos("רק שרוצה לוודא שהגעת.") == "רק רוצה לוודא שהגעת.")
check("(c) regression: ordinary text containing real, unrelated words "
      '("לעיר", "רוצה לוודא") on their own is never touched',
      chat._fix_known_typos("טסים לעיר חדשה, ורק רוצה לוודא שהכל מוכן.")
      == "טסים לעיר חדשה, ורק רוצה לוודא שהכל מוכן.")

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DRYRUN5L-J7-FACT-AND-TYPOS TESTS PASSED")
