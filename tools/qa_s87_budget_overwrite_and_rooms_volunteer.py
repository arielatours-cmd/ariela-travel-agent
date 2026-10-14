"""QA for Shaked's live report (2026-10-13, qa-s87, Cyprus, commit 6abcd0d):

1. 🔴 "עד 500 שקל ללילה" (answering the LODGING budget question) clobbered
   an already-known budget_per_person=1500 down to 500. Root cause: the
   bare "עד <number> שקל" flight-budget pattern (added for an earlier,
   unrelated bug - a budget stated with no "לאדם" qualifier) has no anchor
   ruling out a per-night mention, unlike the other two flight-budget
   patterns which require "תקציב" or an explicit "לאדם/לכרטיס" qualifier.
   Fixed by skipping every pattern in _deterministic_budget_facts (and the
   _budget_answer_by_meaning model fallback) once "ליל" appears anywhere -
   the exact cue lodging.details.budget's own parser already keys on.

2. 🟠 "מלון, חדר אחד" (answering a lodging TYPE question, not a rooms
   question) captured only the type, not the room count - the third time
   this exact shape was seen live. _deterministic_lodging_facts only
   recognized a bare "חדר אחד" inside the asked_rooms-gated branch; added
   it to the same unprompted-volunteer fallback that already exists for
   "חדר זוגי".

   Also: after that gap stayed open, Tinkerbell's own closing-claim safety
   net offered lodging as an undecided yes/no choice ("תרצי שאעזור גם עם
   לינה, או שזה הכל להפעם?") even though lodging was genuinely ACTIVE with
   a real open gap - mid-conversation, not an optional domain waiting to
   be offered. Fixed: when pending_domain is the genuinely active session
   (not an undecided next_session) and it has a real open gap, ask the
   concrete gap question instead of the generic offer.

3. 🟡 Route-base extraction from approved_text grabbed a trailing time-of-
   day word too ("פאפוס בערב" instead of "פאפوס", from "...חזרה ללינה
   בפאפוס בערב"). Added בערב/בבוקר/בצהריים/בלילה to the same exclusion
   that already keeps "ללילה" out.

Run: python3 tools/qa_s87_budget_overwrite_and_rooms_volunteer.py
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


# --- 1a. The exact qa-s87 shape: a per-night lodging budget answer never
#         resolves anything for the flight's per-person budget ---
check("'עד 500 שקל ללילה' never resolves a flight budget_per_person",
      chat._deterministic_budget_facts("עד 500 שקל ללילה") == {})

# --- 1b. Regression guard: the original bare-pattern bug fix (no "ליל")
#         still works exactly as before ---
check("'עד 5000 שקל' with no night mention still resolves the flight budget",
      chat._deterministic_budget_facts("עד 5000 שקל") == {"budget_per_person": {"amount": 5000, "currency": "ILS", "status": "known"}})

# --- 1c. Regression guard: the explicit-qualifier and תקציב-word patterns
#         still work too ---
check("'תקציב של 4000 לאדם' still resolves normally",
      chat._deterministic_budget_facts("תקציב של 4000 לאדם")["budget_per_person"]["amount"] == 4000)

# --- 1d. The model-based fallback also never fires against the lodging
#         budget question's own phrasing ---
lodging_budget_history = [{"role": "assistant", "content": "מה התקציב ללילה, או איזו רמת נוחות אתם מחפשים?"}]
check("_budget_answer_by_meaning never fires when the last question was lodging's own (ליל-cued)",
      chat._budget_answer_by_meaning("עד 500", lodging_budget_history, {"budget_per_person": {"amount": None, "status": "unknown"}}) == {})

# --- 2a. "מלון, חדר אחד" volunteers rooms=1 even when the prior question
#         was only about type, not rooms ---
type_question_history = [{"role": "assistant", "content": "איזה סוג לינה מתאים לכם (מלון, דירה או וילה)?"}]
resolved = chat._deterministic_lodging_facts("מלון, חדר אחד", type_question_history)
check("'מלון, חדר אחד' captures both type and rooms, not just type",
      resolved.get("lodging", {}).get("details", {}).get("type") == "מלון"
      and resolved.get("lodging", {}).get("details", {}).get("rooms") == 1)

# --- 2b. Regression guard: an explicit number of rooms still parses when
#         actually asked ---
rooms_question_history = [{"role": "assistant", "content": "כמה חדרים תרצו?"}]
check("'3 חדרים' after the real rooms question still resolves to 3",
      chat._deterministic_lodging_facts("3 חדרים", rooms_question_history).get("lodging", {}).get("details", {}).get("rooms") == 3)

# --- 2c. closing-claim safety net: a genuinely ACTIVE lodging session with
#         a real open gap gets the concrete gap question, not a yes/no
#         "want lodging too?" offer ---
active_lodging_state = {
    "active_session": "lodging",
    "next_session": None,
    "requested_services": ["flights", "lodging"],
    "service_decisions": {"flights": {"wanted": True}, "lodging": {"wanted": True}},
    "destination": {"places": ["קפריסין"]},
    "destination_airports": ["LCA"],
    "dates": {"departure": "2026-12-06", "return": "2026-12-11"},
    "travelers": {"adults": 2},
    "trip_type": "standard",
    "session_status": {"flights": "complete", "lodging": "active", "car": "complete", "trip_planning": "complete"},
    "lodging": {"details": {"type": "מלון", "rooms": None, "locations": "פאפוס", "budget": 500}},
}
gaps = chat._session_gaps(active_lodging_state, "lodging")
check("precondition: lodging genuinely has an open gap (rooms) in this state", gaps == ["lodging.details.rooms"])
check("the real gap question is known for this active, still-open lodging gap",
      chat._GAP_QUESTION_TEXT.get(gaps[0]) == "כמה חדרים תרצו?")

# --- 3a. Route-base extraction trims a trailing time-of-day word, not just
#         the duration-phrase words already handled ---
check("'...חזרה ללינה בפאפוס בערב' extracts the bare place name, not 'פאפוס בערב'",
      chat._extract_route_bases_from_approved_text("חזרה ללינה בפאפוס בערב.") == ["פאפוס"])

# --- 3b. Regression guard: the original qa-s84 extraction still works ---
check("the original qa-s84 multi-base extraction is unaffected",
      chat._extract_route_bases_from_approved_text(
          "לינה באזור לרנקה ללילה הראשון, לינה בלימסול לשני הלילות הבאים, ולינה בפאפוס לשני הלילות האחרונים."
      ) == ["לרנקה", "לימסול", "פאפוס"])

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL QA-S87 FIXES PASSED")
