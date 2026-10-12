"""QA for Shaked's live report (2026-10-12, round on f2ecfed): after a route
is approved, "מצוין, המסלול מאושר. תרצי שאמשיך גם עם לינה?" kept appearing
even when the customer had already said "גם לינה ורכב" in their very first
message (scenario 11: "צריכה רק תכנון מסלול בטוסקנה ולינה"; scenario 12:
"נשמח לתכנון מסלול, לינה ורכב שכור").

Root cause: the route-approval reply in chat_clean() (ariella_chat_clean.py)
only skipped the yes/no offer for a domain already "complete"/"declined" -
but _sessionize_state auto-promotes a domain straight to "active" (not
"pending") once its service_decisions.wanted is True and flights is
settled. An "active" domain is a DECIDED one (just not detail-complete
yet), so re-asking "do you want this too?" re-asks an already-answered
question. The fix made the yes/no offer conditional on the domain still
being genuinely "pending" (undecided); an "active" domain now hands off to
Tinkerbell directly instead.

This tests the precondition the fix depends on - that _sessionize_state
really does mark an already-wanted domain "active" (not "pending") once
flights are settled, and leaves a genuinely undecided domain "pending" -
using the real functions, no mocking needed.

Run: python3 tools/qa_route_approval_skips_decided_offer.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

from ariella_chat_clean import _sessionize_state, _advance_sessions

# --- 1. Lodging+car already requested up front (scenario 12) -> both "active" ---
state = {
    "session_status": {"flights": "complete", "trip_planning": "active", "lodging": "pending", "car": "pending"},
    "service_decisions": {
        "flights": {"wanted": True, "source": "destination_implies_flights"},
        "trip_planning": {"wanted": True, "source": "explicit_named_accept"},
        "lodging": {"wanted": True, "source": "explicit_named_accept"},
        "car": {"wanted": True, "source": "explicit_named_accept"},
    },
    "requested_services": ["flights", "trip_planning", "lodging", "car"],
    "destination": {"places": "טוסקנה"},
}
sessionized = _sessionize_state(dict(state))
assert sessionized["session_status"]["lodging"] == "active", sessionized["session_status"]
assert sessionized["session_status"]["car"] == "active", sessionized["session_status"]
print("PASS: lodging+car already wanted up front -> both land on 'active', not 'pending' (so the yes/no offer must be skipped for them)")

# --- 2. Only lodging requested up front (scenario 11), car genuinely undecided ---
state2 = {
    "session_status": {"flights": "complete", "trip_planning": "active", "lodging": "pending", "car": "pending"},
    "service_decisions": {
        "flights": {"wanted": True, "source": "destination_implies_flights"},
        "trip_planning": {"wanted": True, "source": "explicit_named_accept"},
        "lodging": {"wanted": True, "source": "explicit_named_accept"},
    },
    "requested_services": ["flights", "trip_planning", "lodging"],
    "destination": {"places": "טוסקנה"},
}
sessionized2 = _sessionize_state(dict(state2))
assert sessionized2["session_status"]["lodging"] == "active", sessionized2["session_status"]
assert sessionized2["session_status"]["car"] == "pending", sessionized2["session_status"]
print("PASS: lodging decided, car genuinely undecided -> lodging 'active' (skip offer), car stays 'pending' (offer still correct)")

# --- 3. Nothing decided yet -> both stay "pending" (ordinary case, offer is correct) ---
state3 = {
    "session_status": {"flights": "complete", "trip_planning": "active", "lodging": "pending", "car": "pending"},
    "service_decisions": {"flights": {"wanted": True, "source": "destination_implies_flights"}},
    "requested_services": ["flights"],
    "destination": {"places": "טוסקנה"},
}
sessionized3 = _sessionize_state(dict(state3))
assert sessionized3["session_status"]["lodging"] == "pending", sessionized3["session_status"]
assert sessionized3["session_status"]["car"] == "pending", sessionized3["session_status"]
print("PASS: nothing decided yet -> both stay 'pending' (ordinary yes/no offer is still the right behavior)")

print("\nALL ROUTE-APPROVAL ALREADY-DECIDED-DOMAIN TESTS PASSED")
