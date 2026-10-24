"""QA for dry-run 5d item 3 (Shaked, 23.10.2026, qa/reports/2026-10-23-
dryrun5d.md, scenario B) root cause - the deeper half of the finding:

Turn 4: baggage (the last FLIGHT-specific required field) was just
answered, but accessibility (a universal, domain-INDEPENDENT guided
field - _GUIDED_DOMAIN_INDEPENDENT_FIELDS) was still genuinely unasked,
having been deliberately jumped ahead of by the mixed-baggage flow
earlier in the conversation. _advance_sessions's own completion check
(`if active and not _session_gaps(state, active): statuses[active] =
"complete"`) only ever checks flights/lodging/car's OWN per-domain
fields via _session_gaps - accessibility deliberately lives OUTSIDE any
one domain's gap list by design, so it was never consulted here at all.
The live result: flights closed itself and state.next_session was set
to "trip_planning" in the SAME turn the arbiter was ALSO correctly
telling Tinkerbell to ask accessibility - she tried to answer both,
producing a reply with a dangling accessibility-disclaimer fragment and
no real question, immediately followed by a premature trip_planning
offer. The next turn's "לא" (answering the stray trip_planning offer)
then got recorded as accessibility.needed=False - a plain answer to a
question that was never actually, cleanly asked.

This exact cross-cutting gate (_guided_incomplete_fields) ALREADY
protects ready_for_summary (Shaked's run-11 fix) - this fix extends the
SAME check to gate a single domain closing too, not just the final
all-four-domains summary moment.

Run: python3 tools/qa_dryrun5d_accessibility_blocks_session_close.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import ariella_chat_clean as chat  # noqa: E402

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


# Scenario B's exact shape: every FLIGHT-specific field is known (dates,
# travelers, departure_airport, connection_preference, baggage, budget),
# but accessibility was jumped ahead of by the mixed-baggage flow and is
# still genuinely open.
FLIGHTS_STATE_ACCESSIBILITY_OPEN = {
    "requested_services": ["flights"],
    "service_decisions": {"flights": {"wanted": True}},
    "trip_type": "standard",
    "destination": {"places": ["זלצבורג"], "mode": "specific", "status": "known"},
    "destination_airports": ["SZG"],
    "dates": {"departure": "2026-11-21", "return": "2026-11-25", "needs_confirmation": False},
    "travelers": {"adults": 2, "children": 0},
    "departure_airport": "TLV",
    "flight": {"connection_preference": "אין העדפה", "baggage": ["checked_bag"]},
    "budget_per_person": {"amount": 1400, "currency": "ILS", "status": "known"},
    "session_status": {"flights": "active", "lodging": "pending", "car": "pending", "trip_planning": "pending"},
    "active_session": "flights",
    "guided": {"current_question": "accessibility", "attempts": 0, "answered": ["dates", "travelers", "baggage"]},
}

check("precondition: every flight-specific gap is genuinely closed (confirms the test state "
      "actually reaches the completion check at all)",
      chat._session_gaps(FLIGHTS_STATE_ACCESSIBILITY_OPEN, "flights") == [])
check("precondition: accessibility is genuinely the one remaining cross-cutting gap",
      chat._guided_incomplete_fields(FLIGHTS_STATE_ACCESSIBILITY_OPEN) == ["accessibility"])

result = chat._advance_sessions(dict(FLIGHTS_STATE_ACCESSIBILITY_OPEN))
check("scenario B root-cause FIX: flights does NOT close itself while accessibility is still "
      "genuinely open, even though every flight-specific field is known",
      result.get("session_status", {}).get("flights") != "complete")
check("scenario B root-cause FIX: active_session stays 'flights' - never silently cleared",
      result.get("active_session") == "flights")
check("scenario B root-cause FIX: next_session is never set to trip_planning while accessibility "
      "is still open - no premature, competing offer this turn",
      result.get("next_session") is None)
check("scenario B root-cause FIX: missing_required still correctly reflects the flight-specific "
      "gaps as empty (accessibility is reported via guided.current_question/_guided_ask_hint, "
      "never via missing_required)",
      result.get("missing_required") == [])

# Regression: once accessibility IS answered (the normal, non-jumped-queue
# case), flights closes exactly as before - nothing broke the ordinary flow.
FLIGHTS_STATE_ACCESSIBILITY_ANSWERED = dict(
    FLIGHTS_STATE_ACCESSIBILITY_OPEN,
    accessibility={"asked": True, "needed": False},
    guided={"current_question": None, "attempts": 0, "answered": ["dates", "travelers", "accessibility", "baggage"]},
)
result_answered = chat._advance_sessions(dict(FLIGHTS_STATE_ACCESSIBILITY_ANSWERED))
check("regression: once accessibility is genuinely answered, flights closes itself exactly as before",
      result_answered.get("session_status", {}).get("flights") == "complete")
check("regression: active_session correctly clears once flights is genuinely complete",
      result_answered.get("active_session") is None)
check("regression: next_session now correctly offers the next pending domain (trip_planning), "
      "since accessibility is no longer blocking it",
      result_answered.get("next_session") == "trip_planning")

# Regression: the gate is scoped to active=="flights" only - lodging/car/
# trip_planning completing is never blocked by accessibility, even when
# it's genuinely still open (by the time either becomes active in the
# normal flow, flights already closed under this same check, so this
# never matters live - but older test fixtures that never modeled
# accessibility at all, because it was never their concern, must keep
# working exactly as before).
LODGING_STATE_ACCESSIBILITY_OPEN = dict(
    FLIGHTS_STATE_ACCESSIBILITY_OPEN,
    active_session="lodging",
    session_status={"flights": "complete", "lodging": "active", "car": "pending", "trip_planning": "pending"},
    requested_services=["flights", "lodging"],
    service_decisions={"flights": {"wanted": True}, "lodging": {"wanted": True}},
    lodging={"interested": "yes", "details": {"type": "מלון", "rooms": 1, "budget": 200, "level": None, "locations": ["זלצבורג"]}},
)
result_lodging = chat._advance_sessions(dict(LODGING_STATE_ACCESSIBILITY_OPEN))
check("regression: lodging completing is never blocked by accessibility (scoped to flights only)",
      result_lodging.get("session_status", {}).get("lodging") == "complete")

# Regression: a session that never needed accessibility at all (e.g. the
# guided steps never cover it this trip) is never wrongly blocked.
FLIGHTS_STATE_NO_ACCESSIBILITY_STEP = dict(FLIGHTS_STATE_ACCESSIBILITY_OPEN)
import unittest.mock as _mock  # noqa: E402
with _mock.patch.object(chat, "_guided_extraction_steps", return_value=set()):
    result_no_step = chat._advance_sessions(dict(FLIGHTS_STATE_NO_ACCESSIBILITY_STEP))
check("regression: when accessibility isn't even a guided step this trip, it never blocks "
      "flights from closing",
      result_no_step.get("session_status", {}).get("flights") == "complete")


# =====================================================================
# Part 2 (lighter, prompt-level mitigation for the SAME scenario B turn-1
# finding): three turns in a row, the baggage hint was correctly handed
# to Tinkerbell with tier-2 arbiter priority, yet her reply asked about
# budget/connection-preference instead - both still genuinely open,
# both still listed in missing_required. TINKERBELL_SYSTEM's own
# standing instruction told her to use missing_required to pick a
# question, with no stated precedence over a specific hint handed to her
# this turn. This is a prompt-compliance mitigation, not a deterministic
# code fix - these checks verify the TEXT is present and reaches every
# guided field's hint, not that a real model actually complies better
# (only a further live dry run can confirm that).
# =====================================================================
check("TINKERBELL_SYSTEM states explicit precedence: a specific hint this turn overrides "
      "missing_required",
      "גוברת על missing_required" in chat.TINKERBELL_SYSTEM)
check("_guided_ask_hint's own baggage-question text reinforces the same override locally",
      "missing_required" in chat._guided_ask_hint("baggage", 0)
      and "missing_required" in chat._guided_ask_hint("baggage", 1))
check("_guided_ask_hint's generic (non-baggage) fields get the same reinforcement too - "
      "this was a systemic gap, not baggage-specific",
      "missing_required" in chat._guided_ask_hint("dates", 0)
      and "missing_required" in chat._guided_ask_hint("travelers", 1))


if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DRYRUN5D-ACCESSIBILITY-BLOCKS-SESSION-CLOSE TESTS PASSED")
