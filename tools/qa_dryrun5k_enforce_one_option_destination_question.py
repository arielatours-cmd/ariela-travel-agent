"""QA for Shaked's dry-run 5k static review (23.10.2026, qa/reports/2026-10-
23-dryrun5k.md, of SHA 4cbe9ab3): J0 and J1 both failed (5/7 overall) for the
SAME root cause - _enforce_one_option_question flags any single question
sentence containing " או " as "bundled" (two separate questions improvised
into one, the failure mode it was actually built to catch) and replaces it
with the generic _flight_gap_question fallback. This silently stomped the
arbiter's own correct, specific destination question - "ברגן (נורווגיה) או
ברגמו (איטליה)?" became "באיזה שדה תרצה לנחות בהלוך?", reproduced live
word-for-word (chat_resp_dr5j0.jsonl).

Root cause: a genuine 2-way destination ambiguity (destination_ambiguous,
"ברגן או ברגמו", "ליון בצרפת או יוון") or a genuinely-unresolved gateway
naming real nearby options (destination_gateway, "פולה או טריאסטה") BOTH
legitimately use " או " to name two real places in ONE sanctioned single
question - the business owner's own "ask once, naming both" format - never
the free-improvised alternative this function exists to catch. Shaked's own
note flagged that the SAME mechanism plausibly also hits destination_gateway
(Pula/Trieste) once active_session="flights" - confirmed live during this
fix, not just theoretical.

Fixed: _enforce_one_option_question asks _turn_question_arbiter directly for
what ACTUALLY won this turn (the same function _call_tinkerbell itself uses)
and returns the reply completely untouched whenever the winning kind is
"destination_ambiguous" or "destination_gateway" - never a bare "is a hint
available in state" check, which could be true even when something else
won the arbiter this turn instead.

UPDATED (23.10.2026, Shaked's static review of 103be976, approved for 5l
with this one follow-up): the original fix's unconditional "return reply
untouched" also disabled "one question per turn" entirely for these two
turns - a reply bundling the destination question with an unrelated SECOND
question ("ברגן (נורווגיה) או ברגמו (איטליה)? ואיזו כבודה תיקחו?") passed
through with both questions intact. Fixed: only the " או " check on the
destination sentence ITSELF is exempted; when more than one question
sentence is present, every sentence other than the one structurally
containing " או " (the arbiter's own sanctioned marker) is still dropped,
exactly like the generic multi-question path.

Run: python3 tools/qa_dryrun5k_enforce_one_option_destination_question.py
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
# J0/J1 FIX: a live _destination_ambiguous_hint means the arbiter's own
# winning question this turn legitimately names two real candidates with
# " או " - must never be replaced by the generic flight-gap fallback.
# =====================================================================
STATE_AMBIGUOUS = {
    "_destination_ambiguous_hint": "dummy",
    "active_session": "flights",
    "dates": {"departure": "2026-12-01", "return": "2026-12-05"},
    "travelers": {"adults": 2, "children": 0, "child_ages": []},
    "departure_airport": "TLV",
    "destination_airports": [],
    "destination": {"places": ["ברגם"], "mode": "specific", "status": "known"},
    "requested_services": ["flights"],
}

BERGEN_BERGAMO_Q = "לאן בדיוק - ברגן (נורווגיה) או ברגמו (איטליה)?"
check("J0 FIX: the arbiter's own Bergen/Bergamo question is never replaced "
      "by the generic 'which airport' fallback",
      chat._enforce_one_option_question(BERGEN_BERGAMO_Q, STATE_AMBIGUOUS) == BERGEN_BERGAMO_Q)

LYON_GREECE_Q = "ליון בצרפת או יוון?"
check("J1 FIX: the arbiter's own Lyon/Greece question is never replaced "
      "by the generic 'which airport' fallback",
      chat._enforce_one_option_question(LYON_GREECE_Q, STATE_AMBIGUOUS) == LYON_GREECE_Q)

# =====================================================================
# Shaked's own flagged (and confirmed live, during this fix) risk: the
# SAME mechanism also stomps a genuinely-unresolved gateway's own
# nearby-options question (destination_gateway tier, not destination_
# ambiguous) once active_session="flights" makes _flight_gap_question
# find something to substitute.
# =====================================================================
STATE_GATEWAY = {
    "destination": {"places": ["רוביניה"], "mode": "specific", "status": "known"},
    "destination_airports": [],
    "active_session": "flights",
    "requested_services": ["flights"],
    "dates": {"departure": "2026-12-01", "return": "2026-12-05"},
    "travelers": {"adults": 2, "children": 0, "child_ages": []},
    "departure_airport": "TLV",
}
PULA_TRIESTE_Q = "לאיזה שדה קרוב תרצו לנחות - פולה או טריאסטה?"
check("FIX (Shaked's own flagged risk, confirmed live): a genuinely-"
      "unresolved gateway's own nearby-options question (Pula/Trieste) is "
      "also never replaced",
      chat._enforce_one_option_question(PULA_TRIESTE_Q, STATE_GATEWAY) == PULA_TRIESTE_Q)

# =====================================================================
# FOLLOW-UP FIX (Shaked's review of 103be976): the destination question
# bundled with an UNRELATED second question in the same reply must still
# have the second question dropped - only the "או" inside the destination
# sentence itself is exempt, not "one question per turn" generally.
# =====================================================================
BUNDLED_WITH_BAGGAGE = "ברגן (נורווגיה) או ברגמו (איטליה)? ואיזו כבודה תיקחו?"
_bundled_result = chat._enforce_one_option_question(BUNDLED_WITH_BAGGAGE, STATE_AMBIGUOUS)
check("FOLLOW-UP FIX: the destination question itself (with its own "
      "sanctioned 'או') is kept",
      "ברגן (נורווגיה) או ברגמו (איטליה)?" in _bundled_result)
check("FOLLOW-UP FIX: the unrelated bundled baggage question is dropped, "
      "not kept alongside it",
      "כבודה" not in _bundled_result)

# =====================================================================
# Regression: an ordinary, genuinely-bundled question UNRELATED to any
# destination topic must still be caught and replaced exactly as before -
# this fix must never disable the mechanism generally, only for the two
# destination-specific arbiter tiers.
# =====================================================================
STATE_UNRELATED = {
    "active_session": "flights",
    "dates": {"departure": "2026-12-01", "return": "2026-12-05"},
    "travelers": {"adults": 2, "children": 0, "child_ages": []},
    "departure_airport": "TLV",
    "destination_airports": ["PRG"],
    "destination": {"places": ["פראג"]},
    "requested_services": ["flights"],
}
check("regression: an ordinary bundled question with nothing to do with "
      "destinations is still caught and replaced, unchanged from before",
      chat._enforce_one_option_question(
          "רוצים טיסה ישירה או שאפשר עם קונקשן?", STATE_UNRELATED
      ) != "רוצים טיסה ישירה או שאפשר עם קונקשן?")

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DRYRUN5K-ENFORCE-ONE-OPTION-DESTINATION-QUESTION TESTS PASSED")
