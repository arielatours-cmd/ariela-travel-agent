"""QA for the business owner's explicit instruction (2026-10-13, relayed by
Shaked after the qa-s79/s80 Cyprus rounds): "אי אפשר להגניס אינסוף דוגמאות
לקוד... צריך לעבוד עם כללים עקרוניים שינחו את השיחה" (you can't keep
stuffing endless examples into the code for every possible phrasing - need
principled rules guiding the conversation instead).

Per that instruction: when the customer answers an open lodging/car/
trip_planning question with no deterministic parser coverage, understand
the MEANING with the model - including relative answers ("השדה שננחת בו")
and bare confirmations ("מתאים", "שניהם") - rather than writing a new
regex for every phrasing. The deterministic parsers stay as a free, fast
first pass and safety net, never the primary source. When genuinely
unsure, ask the customer to confirm with specifics instead of guessing or
repeating the same question verbatim.

This mocks _post_claude (no real network call) and exercises
_understand_open_gap_answer directly: the gating (only lodging/car/
trip_planning, only when real gaps remain, never calling the model
otherwise), the hard safety boundary (a field outside the given gap list
is always dropped, however the model phrases it), and the clarify path.

Run: python3 tools/qa_understand_open_gap_answer.py
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


BASE_STATE = {
    "active_session": "car",
    "requested_services": ["flights", "car"],
    "service_decisions": {"car": {"wanted": True}},
    "destination": {"places": ["קפריסין"]},
    "destination_airports": ["PFO"],
    "return_departure_airports": ["LCA"],
    "dates": {"departure": "2026-12-06", "return": "2026-12-11"},
    "travelers": {"adults": 2},
    "car": {"details": {"vehicle_type": "משפחתי", "transmission": "אוטומטי", "pickup": None, "return": None}},
}
HISTORY = [{"role": "assistant", "content": "באיזה שדה תעופה או עיר תרצו לאסוף את הרכב?"}]


def call(fake_reply, message, state=BASE_STATE, history=HISTORY):
    def fake_post_claude(key, model, system_static, system_dynamic, history_arg, msg, max_tokens, include_history=True, source="other"):
        return fake_reply
    with patch.object(chat, "_post_claude", side_effect=fake_post_claude):
        return chat._understand_open_gap_answer("test-key", "claude-sonnet-5", message, history, state)


# --- 1. Relative answer ("the one we land at / depart from") resolved
#        against the known reference airports given in the prompt ---
resolved, clarify = call(
    json.dumps({"resolved": {"car.details.pickup": "PFO", "car.details.return": "LCA"}, "clarify": None}),
    "באיזה שנחת, וההחזרה איפה שנמריא",
)
check("relative pickup/return answer resolves to known reference codes",
      resolved == {"car": {"details": {"pickup": "PFO", "return": "LCA"}}} and clarify is None)

# --- 2. Hard safety boundary: a field outside the given gap list is
#        always dropped, even if the model returns it ---
resolved2, _ = call(
    json.dumps({"resolved": {"flights.destination_airports": "XXX", "car.details.pickup": "PFO"}, "clarify": None}),
    "פאפוס",
)
check("a field the model wasn't told about is always dropped (never a different domain)",
      resolved2 == {"car": {"details": {"pickup": "PFO"}}})

# --- 3. Clarify path: nothing resolved, a confirmation question instead ---
resolved3, clarify3 = call(
    json.dumps({"resolved": {}, "clarify": "את מתכוונת שהאיסוף וההחזרה יהיו באותו שדה שבו ננחת?"}),
    "בדיוק",
)
check("ambiguous answer -> nothing resolved, a real clarify question returned",
      resolved3 == {} and clarify3 and "שבו ננחת" in clarify3)

# --- 4. Number field (lodging.details.rooms) parses a plain digit out of
#        free text ---
lodging_state = {
    "active_session": "lodging",
    "requested_services": ["flights", "lodging"],
    "service_decisions": {"lodging": {"wanted": True}},
    "destination": {"places": ["קפריסין"]},
    "dates": {"departure": "2026-12-06", "return": "2026-12-11"},
    "travelers": {"adults": 2},
    "lodging": {"details": {"type": "מלון", "rooms": None, "locations": "פאפוס", "budget": 500}},
}
resolved4, _ = call(
    json.dumps({"resolved": {"lodging.details.rooms": "2"}, "clarify": None}),
    "שני חדרים בבקשה",
    state=lodging_state,
    history=[{"role": "assistant", "content": "כמה חדרים תרצו?"}],
)
check("number-type gap parses the model's own resolved numeric value",
      resolved4 == {"lodging": {"details": {"rooms": 2}}})

# --- 5. Gating: wrong active domain (flights) -> skipped, no API call ---
flights_state = dict(BASE_STATE, active_session="flights")
called = {"n": 0}
def fake_post_claude_counter(*a, **kw):
    called["n"] += 1
    return "{}"
with patch.object(chat, "_post_claude", side_effect=fake_post_claude_counter):
    resolved5, clarify5 = chat._understand_open_gap_answer("test-key", "claude-sonnet-5", "פאפוס", HISTORY, flights_state)
check("active_session='flights' -> skipped entirely, no model call", resolved5 == {} and clarify5 is None and called["n"] == 0)

# --- 6. Gating: no gaps left in the active domain -> skipped, no API call ---
no_gap_state = dict(BASE_STATE)
no_gap_state["car"] = {"details": {"vehicle_type": "משפחתי", "transmission": "אוטומטי", "pickup": "PFO", "return": "LCA"}}
called2 = {"n": 0}
with patch.object(chat, "_post_claude", side_effect=fake_post_claude_counter):
    resolved6, clarify6 = chat._understand_open_gap_answer("test-key", "claude-sonnet-5", "תודה", HISTORY, no_gap_state)
check("no real gaps left -> skipped entirely, no model call (cost discipline)", resolved6 == {} and clarify6 is None and called2["n"] == 0)

# --- 7. A malformed/non-JSON model reply never crashes - just resolves nothing ---
resolved7, clarify7 = call("זה לא JSON בכלל", "פאפוס")
check("malformed model reply never crashes, resolves nothing", resolved7 == {} and clarify7 is None)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL UNDERSTAND-OPEN-GAP-ANSWER TESTS PASSED")
