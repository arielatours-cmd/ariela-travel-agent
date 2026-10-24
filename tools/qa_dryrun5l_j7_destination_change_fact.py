"""QA for Shlomo's 5l follow-up list (23.10.2026, relayed after Shaked's
qa/reports/2026-10-23-dryrun5l.md, SHA 2084d74 on branch `shaked`, 4/4 pass):
items (a) and (b) of a 3-item follow-up list queued for a PR before round
13 - item (c) (two model-wording-typo regex fixes) was REMOVED per
Shlomo's explicit instruction (24.10.2026, review of bda9ef35): it
violates the business owner's standing rule - no word lists, regex, or
fixed sentences correcting the model's own free-text output. _fix_known_
typos's existing נתב"ג/יעדיפות entries predate that rule and are
grandfathered, but no new ones get added for a single observed typo; if
either glitch recurs, the fix is a better instruction to the model, not
another regex.

(a) J7 ("וינה -> פראד"): PRG is saved to trip_update in the SAME turn
(destination_change with verified=true), but Tinkerbell's reply hedged -
"ברור, פראג זה יעד נהדר לינואר. רק רוצה לוודא שהעדכון ליעד אכן נקלט אצלי
לפני שנמשיך - בינתיים אני ממשיכה לבדוק את זה." - describing a save that
already happened as still in progress. Root cause (Shaked's own
hypothesis): TINKERBELL_SYSTEM's instruction never to confirm an unsaved
destination change is correct, but the raw state JSON dump alone gives no
EXPLICIT signal that THIS turn is when it was saved, so the model hedges
defensively. Fixed (first attempt, SHA 7fb03d9e): set the one-turn marker
inside _run_destination_recognition's own already-settled-correction
branch.

REJECTED by Shaked's re-review of 7fb03d9e (same report, SHA 2084d74 on
branch `shaked`): that branch never runs for the REAL live J7 turn at all.
In J7, the extractor's own evidence ("פראד") is already a verbatim quote
present in the message, so _resolve_destination_by_meaning's OWN
already_settled/places_changed branch finds verified_evidence=True and
closes the change right there - _run_destination_recognition is never
even reached. Confirmed by replaying trip_update from qa-dryrun 763e540's
real turn 1 (chat_resp_dr5l7.jsonl): places=['פראג'] with evidence
'פראד' produced _destination_change_confirmed_fact=None and 0 model
calls. Fixed for real this time: the marker is now also set directly in
that branch (the ONLY place that actually closes a genuine, already-
verified destination change this turn) - whichever of places_changed/
airports_changed actually carried the new value. Surfaced via the new
_destination_change_confirmed_fact_text(state) as an explicit FACT
sentence in system_dynamic - the same "state, not model inference"
pattern used by every other deterministic fact in this file. Checked
(and confirmed NOT needed): J6's silent destination-change path returns
its own composed reply directly without ever calling _call_tinkerbell at
all, so it already gets the same explicit-confirmation outcome for free.
Popped at the top of _resolve_destination_by_meaning so it never survives
into a second turn's trip_state.

(b) Narrow the _enforce_one_option_question destination exemption so only
the "או" check on the destination sentence itself is exempted, not "one
question per turn" generally - covered by
tools/qa_dryrun5k_enforce_one_option_destination_question.py's own
follow-up checks (added same round), not repeated here.

Run: python3 tools/qa_dryrun5l_j7_destination_change_fact.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

from unittest.mock import patch

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
# (a) THE REAL J7 REPRO (Shaked's own re-review, SHA 2084d74): the
# extractor has ALREADY written the corrected spelling (places=['פראג'])
# with its own verbatim evidence quote ("פראד", which genuinely appears
# in the customer's raw message) - this is the already_settled/
# places_changed/verified_evidence=True branch, never _run_destination_
# recognition at all. Mocking _post_claude to raise enforces the exact
# "0 model calls" _resolve_destination_by_meaning's own diagnostic event
# showed for this real turn.
# =====================================================================
VIE_SETTLED_STATE = {
    "destination_airports": ["VIE"],
    "destination": {"places": ["וינה"], "mode": "specific", "status": "known"},
}
REAL_J7_UPDATE = dict(
    VIE_SETTLED_STATE,
    destination={"places": ["פראג"], "mode": "specific", "status": "known"},
)

def _fail_if_called(*_a, **_kw):
    raise AssertionError("no model call should happen on the real J7 path")


with patch.object(chat, "_post_claude", side_effect=_fail_if_called):
    real_j7_result = chat._resolve_destination_by_meaning(
        VIE_SETTLED_STATE, dict(REAL_J7_UPDATE), "פראד", "בעצם נעדיף פראד", [])
check("(a) REAL J7 FIX: the extractor's own already-verified correction "
      "(no model call at all) sets the same explicit confirmed-fact "
      "marker, matching the live diagnostic (places_changed, "
      "verified=true)",
      real_j7_result.get("_destination_change_confirmed_fact") == "פראג")
check("(a) REAL J7 regression: the destination itself is still saved "
      "exactly as before (places=['פראג'])",
      (real_j7_result.get("destination") or {}).get("places") == ["פראג"])

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

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DRYRUN5L-J7-DESTINATION-CHANGE-FACT TESTS PASSED")
