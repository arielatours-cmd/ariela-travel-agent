"""QA for Shaked's live report (2026-10-13, qa-s85, Cyprus, commit 34941c3 -
discovered mid-run when s85 itself was cut short by a mid-run deploy, so
she restarted clean as s86):

1. 🟠 flight.connection_preference had no deterministic writer at all - only
   the extractor's own JSON ever set it. A combined answer ("ישירה, ומזוודה
   לכל אחד" - direct, and luggage for everyone) to the combined direct/
   baggage question captured only the baggage half; connection_preference
   stayed null. Added _deterministic_connection_preference_facts, gated on
   the prior assistant message actually using the standard ישירה/קונקשן
   framing (_flight_gap_question's own wording), mirroring the existing
   car.details.vehicle_type/transmission deterministic backstops.

2. 🟠 After that gap stayed open, Tinkerbell later wrote "הטיסה סגורה
   מבחינתי" (the flight is settled as far as I'm concerned) with
   active_session still "flights" and missing_required still genuinely
   listing flight.connection_preference - a false domain-closure claim.
   Added _redirect_false_flight_closure_claim, the mirror image of the
   existing _redirect_reopened_closed_domain_question safety net: swaps in
   the real, concrete gap question instead of letting the false claim
   through.

Run: python3 tools/qa_s85_connection_preference_and_false_closure.py
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


COMBINED_QUESTION_HISTORY = [
    {"role": "assistant", "content": "חשוב לכם שהטיסה תהיה ישירה, או שקונקשן גם בסדר? וכמה כבודה תצטרכו?"}
]

# --- 1a. The exact qa-s85 shape: a combined answer's direct-flight half is
#         captured deterministically, not just the baggage half ---
resolved = chat._deterministic_connection_preference_facts("ישירה, ומזוודה לכל אחד", COMBINED_QUESTION_HISTORY)
check("'ישירה' in a combined answer resolves flight.connection_preference='direct'",
      resolved == {"flight": {"connection_preference": "direct"}})

# --- 1b. "no preference" phrasing also resolves (so the gap can close
#         either way, not only when the customer wants direct) ---
resolved_np = chat._deterministic_connection_preference_facts("לא משנה לי, קונקשן בסדר", COMBINED_QUESTION_HISTORY)
check("'לא משנה לי' resolves to a real (non-null) no-preference value",
      resolved_np.get("flight", {}).get("connection_preference") not in (None, ""))

# --- 1c. A negated "לא ישירה" ("not direct") is read as no-preference, not
#         mistakenly flipped into a direct-only request ---
resolved_neg = chat._deterministic_connection_preference_facts("לא חייבת ישירה, קונקשן בסדר", COMBINED_QUESTION_HISTORY)
check("'לא חייבת ישירה' never resolves to connection_preference='direct'",
      resolved_neg.get("flight", {}).get("connection_preference") != "direct")

# --- 1d. Gating: the prior question wasn't actually about direct/connection
#         at all -> never fires, even if the word 'ישירה' appears elsewhere ---
unrelated_history = [{"role": "assistant", "content": "כמה חדרים תרצו?"}]
check("no direct/קונקשן framing in the prior question -> never fires",
      chat._deterministic_connection_preference_facts("ישירה בבקשה", unrelated_history) == {})

# --- 2a. The exact qa-s85 false-closure shape: active_session='flights'
#         with a real open connection_preference gap -> the false claim is
#         replaced with the real concrete question ---
flights_state = {
    "active_session": "flights",
    "requested_services": ["flights"],
    "service_decisions": {"flights": {"wanted": True}},
    "destination": {"places": ["קפריסין"]},
    "destination_airports": ["LCA", "PFO"],
    "dates": {"departure": "2026-12-06", "return": "2026-12-11"},
    "travelers": {"adults": 2},
    "departure_airport": "TLV",
    "trip_type": "standard",
    "flight": {"connection_preference": None, "baggage": ["checked_bag"]},
    "budget_per_person": {"amount": 1500, "currency": "₪", "status": "known"},
}
false_claim_reply = "מעולה, עד 1500 לאדם נרשם. הטיסה סגורה מבחינתי - עוברים הלאה."
fixed = chat._redirect_false_flight_closure_claim(false_claim_reply, flights_state)
check("a false 'הטיסה סגורה' claim with a real open gap is replaced with the real question",
      fixed == chat._flight_gap_question(chat._session_gaps(flights_state, "flights"), flights_state))
check("the replacement is never the false claim itself", fixed != false_claim_reply)

# --- 2b. No real gap left -> the claim is actually true, so the reply
#         passes through unchanged ---
closed_state = dict(flights_state)
closed_state["flight"] = {"connection_preference": "direct", "baggage": ["checked_bag"]}
check("no real gap left (flight is genuinely closed) -> reply passes through unchanged",
      chat._redirect_false_flight_closure_claim(false_claim_reply, closed_state) == false_claim_reply)

# --- 2c. active_session isn't 'flights' at all -> never fires ---
lodging_state = dict(flights_state, active_session="lodging")
check("active_session != 'flights' -> never fires",
      chat._redirect_false_flight_closure_claim(false_claim_reply, lodging_state) == false_claim_reply)

# --- 2d. An ordinary reply that doesn't make this specific false claim is
#         never touched ---
normal_reply = "חשוב לכם שהטיסה תהיה ישירה, או שקונקשן גם בסדר?"
check("an ordinary on-topic reply is never touched",
      chat._redirect_false_flight_closure_claim(normal_reply, flights_state) == normal_reply)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL QA-S85 FIXES PASSED")
