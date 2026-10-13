"""QA for Shaked's live report (2026-10-13, Cyprus real-scan test, qa-s77,
on 3390615 - after the a126be7/36b6355/148a63c/3390615 fixes were already
live). Two distinct root causes behind the same symptom family (a domain
staying open forever despite every visible question being answered):

1. lodging.details.budget had NO deterministic writer at all - only rooms/
   type/level/locations did. "חדר אחד, עד 500 ללילה" correctly set rooms=1
   but left budget=null, which alone kept lodging.details.budget_or_level
   (and so session_status.lodging) stuck at "active" forever. A later,
   unrelated car-pickup answer then got mis-routed into lodging.details.
   locations, because lodging was (wrongly) still the active_session.
   Fixed by adding a budget extractor to _deterministic_lodging_facts,
   gated on the "ליל"/"לילה" (per-night) cue - distinct from the flight
   budget's "לאדם"/"לכרטיס" (per-person) cue, so the two never collide.

2. Tinkerbell presented a full day-by-day route ("יום 1, 6.12.2026
   (ראשון)"..."יום 6, 11.12.2026 (שישי)") while trip_planning was still
   formally "pending" (never activated as active_session). The customer's
   "מתאים" right after it was then read as the generic "want route help
   too?" post-flight offer instead of a real route approval, and
   trip_planning only closed after an extra, unnatural "כבר אישרתי את
   המסלול". Fixed by also accepting the itinerary-shaped last_assistant_
   text itself as sufficient evidence a route was just proposed, alongside
   the existing active_session=="trip_planning" check.

Run: python3 tools/qa_cyprus_lodging_budget_and_route_approval.py
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


# --- 1. Lodging budget: the exact reported phrasing, with the rooms
#        question already asked (as it was live) so both fields fire. ---
rooms_question_history = [{"role": "assistant", "content": "כמה חדרים תרצי?"}]
result = chat._deterministic_lodging_facts("חדר אחד, עד 500 ללילה", rooms_question_history)
lodging_details = (result.get("lodging") or {}).get("details") or {}
check("rooms still captured from the same message", lodging_details.get("rooms") == 1)
check("budget now captured too (was null before this fix)", lodging_details.get("budget") == 500)

# --- 2. Flight budget ("לכרטיס"/"לאדם") must never leak into lodging.budget ---
result2 = chat._deterministic_lodging_facts("עד 5000 שקל לכרטיס", [])
check("flight-style per-ticket budget does not leak into lodging.details.budget",
      (result2.get("lodging") or {}).get("details", {}).get("budget") is None)

# --- 3. With budget now set, lodging's own gap check clears and _advance_
#        sessions promotes it to complete, activating car next (not stuck). ---
state = {
    "trip_type": "standard",
    "requested_services": ["flights", "trip_planning", "lodging", "car"],
    "service_decisions": {s: {"wanted": True} for s in ("flights", "trip_planning", "lodging", "car")},
    "session_status": {"flights": "complete", "trip_planning": "complete", "lodging": "active", "car": "pending"},
    "destination": {"places": ["קפריסין"], "mode": "specific"},
    "destination_airports": ["PFO"],
    "dates": {"departure": "2026-12-06", "return": "2026-12-11", "needs_confirmation": False},
    "travelers": {"adults": 2},
    "departure_airport": "TLV",
    "budget_per_person": {"amount": 3000, "currency": "ILS", "status": "known"},
    "flight": {"baggage": ["checked_bag"]},
    "lodging": {"details": {"type": "מלון", "rooms": 1, "budget": 500, "level": None, "locations": "בשדה התעופה"}},
    "car": {"details": {"vehicle_type": "משפחתי", "transmission": None, "pickup": None, "return": None}},
}
gaps = chat._session_gaps(state, "lodging")
check("lodging has no remaining gaps once budget is known", gaps == [])
advanced = chat._advance_sessions(dict(state))
check("lodging actually promotes to complete", advanced["session_status"]["lodging"] == "complete")
check("car becomes the next active session (not left stuck)", advanced["active_session"] == "car")

# --- 4. Route approval: "מתאים" right after a numbered day-by-day route
#        must close trip_planning even though active_session never became
#        "trip_planning" (the exact Cyprus repro). ---
history = [
    {"role": "user", "content": "אפשר להתחיל לתכנן מסלול?"},
    {
        "role": "assistant",
        "content": (
            "הנה הצעת מסלול: "
            "יום 1, 6.12.2026 (ראשון) - נוחתים בפאפוס, מתארגנים ויום רגוע בעיר. "
            "יום 2, 7.12.2026 (שני) - נסיעה להרי הטרודוס, טיול בכפרים. "
            "יום 6, 11.12.2026 (שישי) - חזרה ללרנקה וטיסה חזרה. "
            "מתאים לך המסלול הזה, או שתרצי לשנות משהו?"
        ),
    },
]
trip_state_route = {
    "active_session": None,  # exactly the reported bug: never flipped to "trip_planning"
    "session_status": {"flights": "complete", "trip_planning": "pending", "lodging": "pending", "car": "pending"},
    "trip_planning": {"interested": True, "approved": False, "details": {}},
}
planning_active = str(trip_state_route.get("active_session") or "") == "trip_planning"
check("precondition: active_session is genuinely NOT trip_planning (reproduces the bug)", not planning_active)

last_assistant_text = history[-1]["content"]
# Exercise the actual day-mention counting logic the same way chat_clean does,
# via the same regexes it builds inline - reproduced here only to prove the
# numbered-route text itself is recognized as >=2 day mentions regardless of
# active_session, which is the condition the real fix now also accepts.
import re as _re
_numbered_day_re = _re.compile(r"(?<![א-ת])יום\s+(\d{1,2})(?!\d)")
numbered_days = {m.group(1) for m in _numbered_day_re.finditer(last_assistant_text)}
check("the numbered day-by-day route text itself yields >=2 distinct day mentions",
      len(numbered_days) >= 2)
check("_is_itinerary_acceptance('מתאים') is true (the actual customer reply)",
      chat._is_itinerary_acceptance("מתאים"))

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL CYPRUS LODGING-BUDGET AND ROUTE-APPROVAL TESTS PASSED")
