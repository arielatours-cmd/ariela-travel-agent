"""QA for Shaked's live report (2026-10-13, qa-s84 item 3, confirmed via an
actual state dump before any fix was attempted): with active_session=
"lodging" and real open lodging gaps (rooms/locations), and flights already
session_status="complete" with flight.connection_preference already
"direct", Tinkerbell still asked "עכשיו נשלים את פרטי הטיסה - חשוב לך שתהיה
ישירה, או שקונקשן גם בסדר?" - reopening an already-settled flight fact
instead of asking about lodging's own still-open gap. Confirmed this was
not a gap-computation bug (the state was identical and correct before and
after that reply) - Tinkerbell's own free text just drifted off-topic.

Added _redirect_reopened_closed_domain_question as a safety net, mirroring
the existing premature-approval one: swap in the real gap question for the
domain that's actually still active and open, whenever the reply's topic
belongs to a domain that's already complete.

Run: python3 tools/qa_redirect_reopened_closed_domain_question.py
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


BASE_STATE = {
    "active_session": "lodging",
    "requested_services": ["flights", "lodging"],
    "service_decisions": {"flights": {"wanted": True}, "lodging": {"wanted": True}},
    "destination": {"places": ["קפריסין"]},
    "destination_airports": ["LCA"],
    "dates": {"departure": "2026-12-06", "return": "2026-12-11"},
    "travelers": {"adults": 2},
    "departure_airport": "TLV",
    "trip_type": "standard",
    "flight": {"connection_preference": "direct", "baggage": ["checked_bag"]},
    "session_status": {"flights": "complete", "lodging": "active", "car": "complete", "trip_planning": "complete"},
    "lodging": {"details": {"type": "מלון", "rooms": None, "locations": None, "budget": 500}},
}

# --- 1. The exact qa-s84 shape: reopens a closed flight fact while lodging
#        has real open gaps -> redirected to the real lodging gap question ---
leaked_reply = (
    "לגבי שעות האיסוף וההחזרה... נקבע אותן לפי הטיסה בזמן ההזמנה.\n\n"
    "עכשיו נשלים את פרטי הטיסה - חשוב לך שתהיה ישירה, או שקונקשן גם בסדר?"
)
fixed = chat._redirect_reopened_closed_domain_question(leaked_reply, BASE_STATE)
check("a reopened closed-flight-fact question gets redirected to the real active-domain gap",
      fixed == chat._GAP_QUESTION_TEXT["lodging.details.rooms"])

# --- 2. No real gap in the active domain -> reply passes through unchanged
#        (nothing safe to redirect to) ---
no_gap_state = dict(BASE_STATE)
no_gap_state["lodging"] = {"details": {"type": "מלון", "rooms": 2, "locations": "פאפוס", "budget": 500}}
unchanged = chat._redirect_reopened_closed_domain_question(leaked_reply, no_gap_state)
check("no open gap in the active domain -> reply passes through unchanged",
      unchanged == leaked_reply)

# --- 3. The reply doesn't actually reopen a closed-domain topic at all ---
normal_reply = "כמה חדרים תרצו?"
check("an ordinary on-topic reply is never touched",
      chat._redirect_reopened_closed_domain_question(normal_reply, BASE_STATE) == normal_reply)

# --- 4. active_session is flights itself -> never redirects (flights is
#        never the "closed domain" relative to itself) ---
flights_active_state = dict(BASE_STATE, active_session="flights")
check("active_session='flights' -> never triggers this safety net",
      chat._redirect_reopened_closed_domain_question(leaked_reply, flights_active_state) == leaked_reply)

# --- 5. flights isn't actually complete yet -> never redirects (it's a
#        legitimate, still-open flights question in that case) ---
flights_open_state = dict(BASE_STATE)
flights_open_state["session_status"] = dict(BASE_STATE["session_status"], flights="active")
check("flights not actually complete -> never redirects a legitimate flights question",
      chat._redirect_reopened_closed_domain_question(leaked_reply, flights_open_state) == leaked_reply)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL REDIRECT-REOPENED-CLOSED-DOMAIN-QUESTION TESTS PASSED")
