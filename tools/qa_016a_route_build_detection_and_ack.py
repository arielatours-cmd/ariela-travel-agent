"""QA for task 016a Stage 2 (ROUTE_BUILD_ASYNC): the detection logic that
decides which chat turns are about to build a full day-by-day route, and
the quick acknowledgement reply sent while that build runs in the
background.

Per Ofek's spec (product/dev-tasks/016a-background-route-build.md): only a
turn that's about to produce a first-draft route or a full rebuild should
go to the background - an ordinary trip_planning question (style/pace) or
waiting on "מאשרת" for an already-proposed route must stay synchronous.
"If in doubt, background it" - but doubt is not license to background
every trip_planning turn, which would make ordinary clarifying questions
needlessly slow and noisy (explicitly called out as its own QA scenario in
the spec: scenario 10, "a normal question at the route stage, not a
rebuild, stays synchronous").

_turn_expected_to_build_route reuses _session_gaps/_sessionize_state - the
SAME gap list that already drives what Tinkerbell's system prompt asks for
next - rather than guessing from the message text, so it can never drift
out of sync with what the model is actually about to be asked to do.

Run: python3 tools/qa_016a_route_build_detection_and_ack.py
"""
import json
import os
import sys
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


def _base_state(**planning_overrides):
    planning_details = {"style": "תרבות ומוזיאונים", "pace": "relaxed"}
    planning_details.update(planning_overrides)
    return {
        "destination": {"places": ["רומא"], "mode": "specific", "status": "known"},
        "dates": {"departure": "2027-06-01", "return": "2027-06-08"},
        "travelers": {"adults": 2, "children": 0},
        "requested_services": ["flights", "trip_planning"],
        "service_decisions": {"flights": {"wanted": True}, "trip_planning": {"wanted": True}},
        "session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "active"},
        "active_session": "trip_planning",
        "trip_planning": {"interested": True, "details": planning_details},
    }


# --- 1. Style+pace known, route still missing: this IS a route-build turn ---
ready_to_build = _base_state()
check(
    "style+pace known, route missing: detected as a route-build turn",
    chat._turn_expected_to_build_route(ready_to_build) is True,
)

# --- 2. Style/pace still missing: NOT a route-build turn (ordinary clarifying question) ---
missing_style = _base_state(style=None, pace=None)
check(
    "style/pace still unknown: NOT a route-build turn (stays synchronous)",
    chat._turn_expected_to_build_route(missing_style) is False,
)

missing_pace_only = _base_state(pace=None)
check(
    "only pace still unknown: NOT a route-build turn",
    chat._turn_expected_to_build_route(missing_pace_only) is False,
)

# --- 3. Route already proposed, waiting on approval: NOT a route-build turn ---
awaiting_approval = _base_state(route="יום 1: נחיתה. יום 2: סיור.")
awaiting_approval["trip_planning"]["approved"] = False
check(
    "route already proposed, waiting on מאשרת: NOT a route-build turn",
    chat._turn_expected_to_build_route(awaiting_approval) is False,
)

# --- 4. Route already proposed AND approved: fully resolved, NOT a route-build turn ---
fully_resolved = _base_state(route="יום 1: נחיתה. יום 2: סיור.")
fully_resolved["trip_planning"]["approved"] = True
check(
    "route already approved: NOT a route-build turn",
    chat._turn_expected_to_build_route(fully_resolved) is False,
)

# --- 5. A rebuild after something cleared the route (destination/plan changed) ---
# Simulates whatever upstream logic invalidates a stale route: style/pace
# survive, route itself goes back to empty - same signal as a first draft.
rebuild_state = _base_state(route=None)
rebuild_state["trip_planning"]["approved"] = False
check(
    "route cleared after a change, style/pace still known: detected as a route-build turn (rebuild)",
    chat._turn_expected_to_build_route(rebuild_state) is True,
)

# --- 6. Not in the trip_planning session at all: never a route-build turn ---
other_session = _base_state()
other_session["requested_services"] = ["flights", "lodging", "trip_planning"]
other_session["service_decisions"]["lodging"] = {"wanted": True}
other_session["session_status"] = {"flights": "complete", "lodging": "active", "car": "declined", "trip_planning": "pending"}
other_session["active_session"] = "lodging"
check(
    "a different active_session entirely: NOT a route-build turn",
    chat._turn_expected_to_build_route(other_session) is False,
)

# --- 7. Garbage/empty input never crashes the detector ---
check("None trip_state: NOT a route-build turn, no crash", chat._turn_expected_to_build_route(None) is False)
check("empty dict: NOT a route-build turn, no crash", chat._turn_expected_to_build_route({}) is False)

# --- 8. The detection probe never mutates the caller's own trip_state dict ---
probe_input = _base_state()
import copy
probe_input_copy = copy.deepcopy(probe_input)
chat._turn_expected_to_build_route(probe_input)
check("detection does not mutate the trip_state dict passed in", probe_input == probe_input_copy)

# --- 9. The ack reply: real call path ---
def _fake_ack_post_claude(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    check("route_ack call uses source='route_ack'", source == "route_ack")
    check("route_ack call caps max_tokens at 60", max_tokens == 60)
    check("route_ack call skips history (include_history=False)", include_history is False)
    return "אני בונה לכם את המסלול עכשיו, רגע קטן!"


with patch.object(chat, "_post_claude", side_effect=_fake_ack_post_claude):
    reply = chat._route_build_ack_reply("תציעי מסלול")
check("a successful ack call returns the model's own sentence", reply == "אני בונה לכם את המסלול עכשיו, רגע קטן!")

# --- 10. The ack reply: fallback on failure ---
def _failing_post_claude(*args, **kwargs):
    raise RuntimeError("simulated failure")


with patch.object(chat, "_post_claude", side_effect=_failing_post_claude):
    fallback_reply = chat._route_build_ack_reply("תציעי מסלול")
check("a failed ack call falls back to the hardcoded sentence, never crashes", fallback_reply == chat._ROUTE_ACK_FALLBACK_TEXT)

# --- 11. The ack reply uses its own fixed ~8s budget, not the website's normal one ---
budget_seen = {}


def _budget_checking_post_claude(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    budget_seen["value"] = getattr(chat._turn_timing, "budget_seconds", None)
    return "בונה את המסלול"


chat._turn_timing.turn_started = __import__("time").time()
with patch.object(chat, "_post_claude", side_effect=_budget_checking_post_claude):
    chat._route_build_ack_reply("תציעי מסלול")
check("the ack call runs under its own 8s budget override", budget_seen.get("value") == chat._ROUTE_ACK_TIMEOUT_SECONDS)
check("the budget override is restored (cleared) after the ack call returns", getattr(chat._turn_timing, "budget_seconds", "unset") is None)
chat._turn_timing.turn_started = None

print()
if FAILED:
    print(f"FAILED ({len(FAILED)}): {FAILED}")
    sys.exit(1)
print("ALL 016A-ROUTE-BUILD-DETECTION-AND-ACK TESTS PASSED")
