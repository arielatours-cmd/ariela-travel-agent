"""QA for Shlomo's relay (21.10.2026) of Shaked's run-9 live diagnostic repro
zd5 ("לדחות ביום" - postpone by a day - after the final summary), REWORKED
after Shaked rejected the first version of this fix (9da376b):

"לראשונה נוצר candidate 13.05–17.05 עם needs_confirmation=True, ואחרי 'כן'
הוא נשמר. ✅ אבל התשובות לא תאמו את ה-state:
- תור 1: 'מתי תרצי לצאת ולחזור?', בלי להציג את ההצעה. ב-missing_required
  היה 'dates'.
- תור 2: אחרי שה-state כבר נשמר, היא ענתה 'תוכלי לציין לי את התאריכים
  המדויקים...'."

Both turns are REPLY/STATE mismatches - the SAVE worked correctly both
times, only the text shown to the customer was wrong.

TURN 1 root cause (unchanged from the first version): the customer's own
message names "הטיסה", which _explicit_service_request's "go back and
change the flight" mechanism reads as a fresh request once nothing else
is "in progress" post-summary - reactivating session_status.flights to
"active". The shift_days mechanism then creates a real pending candidate
this same turn, but _required_state_gaps treats ANY needs_confirmation=
True exactly like "no dates known at all", so "dates" landed in missing_
required/gaps either way, and _flight_gap_question's own "dates" branch
returned the same blind "מתי תרצי לצאת ולחזור?" fallback regardless.

FIRST FIX ATTEMPT (9da376b) REJECTED by Shaked: it built a fixed sentence
here ("מצאתי את זה: X או Y. זה מתאים?"), which broke three separate rules
at once - the business owner's ban on fixed sentences reaching the
customer verbatim, the "never a single yes/no over several options" rule
#120(c)/#124 exist to enforce, and writing the candidate's dates directly
instead of the {{DATE_OPTIONS}} placeholder.

ACTUAL FIX: a pending candidate is never announced through this fixed-text
mechanism at all.
- _flight_gap_question's "dates" branch now returns None (not text) when a
  pending candidate exists, falling through to Tinkerbell's own free-form
  reply.
- _advance_sessions no longer exposes "dates" in missing_required while a
  candidate is genuinely pending (it still correctly keeps the session
  from closing - that check is separate and untouched).
- Tinkerbell gets the real instruction via the PRE-EXISTING _dates_truth_
  hint mechanism (unchanged in this rework): show {{DATE_OPTIONS}}, ask in
  her own words, never a bare yes/no over several options.
- The post-summary reactivation-by-mention itself is NOT touched - per
  Shaked's explicit caution, it may be exactly what let the shift in zd5
  succeed in the first place.

TURN 2 root cause (unchanged from the first version): "כן" resolves the
candidate via _accept_single_proposed_date_range, but _advance_sessions
can close "flights" right back to "complete" (active_session -> None)
WITHIN THIS SAME TURN once dates stop needing confirmation, and _dates_
truth_hint - until the first fix - returned "" the instant active_session
wasn't literally "flights", leaving Tinkerbell with no instruction at all
about dates that had just this turn changed and saved.

FIRST FIX ATTEMPT (9da376b) REJECTED by Shaked: widening unconditionally
to active_session is None also fires at the FINAL summary once the route
is already built (trip_planning complete) - where "never write a calendar
date yourself" would wrongly reach into the itinerary's own per-day dates.

ACTUAL FIX: the None case now excludes whenever session_status.
trip_planning == "complete" - the simpler of the two options Shlomo
offered (vs. "only when flights was the last domain touched this turn"),
a deliberate, acknowledged trade-off: a flight-only date tweak after a
route is already built can still slip through unguided, same as before
this whole mechanism existed for that specific combination.

SECOND REJECTION (be159f6) - turn 1's fix, reworked again: the "pending
candidate" check (needs_confirmation + candidate_ranges) fired on BOTH
shapes alike - a genuine CHANGE to already-known dates, AND the very
first time dates are chosen at all (a relative answer like "בסוף החודש
הבא" produces 2 candidates with departure/return still None - a
different, already-working flow). Dropping "dates" from missing_required
for the first-time shape too let the NEXT gap in the list (Shaked's own
example: budget_per_person) jump the queue and get asked before the
customer's own candidates were ever shown.

ACTUAL FIX: a new shared helper, _dates_pending_change(dates), requires
departure/return to ALSO already be set (a genuine change keeps them at
their last-confirmed values while proposing new ones - a first-time
selection never has them set yet) - used in _advance_sessions' missing_
required filter, so ONLY a real change candidate gets "dates" dropped
from the list; a first-time candidate keeps "dates" fully listed and
answerable, exactly as before any of this work. Separately, _flight_gap_
question's OWN internal gap-priority ladder happened to check "budget_
per_person" (and several other fields) textually before "dates" - a
pre-existing ordering quirk that meant even with "dates" correctly kept
in missing_required, a co-occurring budget_per_person gap could still win
the race inside this one function. Fixed by moving the "pending candidate
(any kind) -> None" check to the very top of the ladder, before every
other gap, so a real candidate always takes priority over any other open
field once one exists.

Run: python3 tools/qa_run9_zd5_post_summary_shift_reply.py
"""
import os
import sys
import json
import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

import ariella_chat_clean as chat
import whatsapp_bridge
from werkzeug.security import generate_password_hash

DB = database.DB_PATH
FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA Run9 ZD5", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


# =====================================================================
# Direct unit coverage: _flight_gap_question's "dates" branch now returns
# None (no fixed text at all) for a pending candidate, never a fixed
# yes/no sentence.
# =====================================================================
_pending_state = {
    "dates": {
        "needs_confirmation": True,
        "candidate_ranges": ["יום חמישי 11.06.2027–יום שני 15.06.2027"],
    },
}
check("zd5 turn-1 FIX: a pending candidate makes _flight_gap_question "
      "return None (no fixed sentence at all) - never announced through "
      "this mechanism",
      chat._flight_gap_question(["dates"], _pending_state) is None)

_pending_two_state = {
    "dates": {
        "needs_confirmation": True,
        "candidate_ranges": [
            "יום חמישי 11.06.2027–יום שני 15.06.2027",
            "יום חמישי 18.06.2027–יום שני 22.06.2027",
        ],
    },
}
check("regression: same None result with two pending candidates",
      chat._flight_gap_question(["dates"], _pending_two_state) is None)

check("regression: no pending candidate at all (genuinely open gap, nothing "
      "known) still falls back to the plain open question",
      chat._flight_gap_question(["dates"], {"dates": {}}) in (
          "מתי תרצה לצאת ולחזור?", "מתי תרצי לצאת ולחזור?",
      ))
check("regression: needs_confirmation True but candidate_ranges empty "
      "(shouldn't normally happen) still falls back to the plain open "
      "question, never raises",
      chat._flight_gap_question(["dates"], {"dates": {"needs_confirmation": True, "candidate_ranges": []}}) in (
          "מתי תרצה לצאת ולחזור?", "מתי תרצי לצאת ולחזור?",
      ))


# =====================================================================
# Direct unit coverage: _advance_sessions keeps "dates" out of missing_
# required while a candidate is pending, WITHOUT letting the session
# close prematurely.
# =====================================================================
_state_with_pending_candidate = {
    "destination": {"places": ["טורינו"], "mode": "specific", "status": "known"},
    "destination_airports": ["TRN"],
    "travelers": {"adults": 2},
    "dates": {"departure": "2027-06-10", "return": "2027-06-14", "needs_confirmation": True,
              "candidate_ranges": ["יום חמישי 11.06.2027–יום שני 15.06.2027"]},
    "requested_services": ["flights"],
    "session_status": {"flights": "active", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
    "active_session": "flights",
    "trip_type": "regular", "departure_airport": "TLV",
    "budget_per_person": {"amount": 2000, "currency": "ILS"},
    "flight": {"baggage": ["checked_bag"], "connection_preference": "no_preference"},
}
_advanced_pending = chat._advance_sessions(dict(_state_with_pending_candidate))
check("zd5 turn-1 FIX: missing_required does NOT list 'dates' while a real "
      "candidate is pending",
      "dates" not in (_advanced_pending.get("missing_required") or []))
check("regression: flights stays active (not prematurely marked complete) - "
      "a pending, unconfirmed candidate is still genuinely unresolved",
      _advanced_pending.get("session_status", {}).get("flights") == "active"
      and _advanced_pending.get("active_session") == "flights")


# =====================================================================
# Direct unit coverage: _dates_pending_change itself, and Shaked's SECOND
# rejection - the conversation-start shape (relative answer -> 2
# candidates, departure/return still None) must be told apart from a
# genuine change to already-known dates.
# =====================================================================
_first_time_dates = {
    "departure": None, "return": None, "needs_confirmation": True,
    "candidate_ranges": [
        "יום חמישי 11.06.2027–יום שני 15.06.2027",
        "יום חמישי 18.06.2027–יום שני 22.06.2027",
    ],
}
_change_dates = {
    "departure": "2027-06-10", "return": "2027-06-14", "needs_confirmation": True,
    "candidate_ranges": ["יום חמישי 11.06.2027–יום שני 15.06.2027"],
}
check("_dates_pending_change is False for a first-time candidate selection "
      "(departure/return still None - nothing confirmed yet)",
      chat._dates_pending_change(_first_time_dates) is False)
check("_dates_pending_change is True for a genuine change (departure/return "
      "already set to the prior confirmed dates)",
      chat._dates_pending_change(_change_dates) is True)

# Shaked's exact second-rejection repro: conversation start, 2 pending
# candidates, destination/travelers known but budget_per_person ALSO still
# a gap - "dates" must stay a real, answerable gap, and the co-occurring
# budget gap must never jump the queue inside _flight_gap_question itself.
check("SECOND REJECTION FIX: _flight_gap_question(['dates','budget_per_person']) "
      "at conversation start (first-time candidates) returns None - NOT the "
      "budget question jumping the queue before the date options are shown",
      chat._flight_gap_question(["dates", "budget_per_person"], {"dates": _first_time_dates}) is None)
check("regression: the same holds regardless of the gaps list's own order",
      chat._flight_gap_question(["budget_per_person", "dates"], {"dates": _first_time_dates}) is None)
check("regression: a genuine change candidate co-occurring with budget_per_person "
      "also never lets budget jump the queue",
      chat._flight_gap_question(["dates", "budget_per_person"], {"dates": _change_dates}) is None)

_first_time_full_state = {
    "destination": {"places": ["רומא"], "mode": "specific", "status": "known"},
    "destination_airports": ["FCO"],
    "travelers": {"adults": 2},
    "dates": _first_time_dates,
    "requested_services": ["flights"],
    "session_status": {"flights": "active", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
    "active_session": "flights",
    "trip_type": "regular", "departure_airport": "TLV",
    "flight": {"baggage": ["checked_bag"], "connection_preference": "no_preference"},
    # budget_per_person deliberately left unset - a real co-occurring gap.
}
_advanced_first_time = chat._advance_sessions(dict(_first_time_full_state))
check("SECOND REJECTION FIX: missing_required KEEPS 'dates' for a "
      "first-time candidate selection (the already-working flow Shaked "
      "named) - only a genuine CHANGE candidate gets it dropped",
      "dates" in (_advanced_first_time.get("missing_required") or []))
check("regression: budget_per_person is still correctly listed too (a real, "
      "separate gap) - just never asked INSTEAD of dates",
      "budget_per_person" in (_advanced_first_time.get("missing_required") or []))


# =====================================================================
# Direct unit coverage: _dates_truth_hint's widened gate (turn 2),
# correctly scoped by trip_planning completion.
# =====================================================================
_confirmed_state_no_active = {
    "active_session": None,
    "session_status": {"flights": "complete", "trip_planning": "declined"},
    "dates": {"departure": "2026-11-28", "return": "2026-12-05", "needs_confirmation": False, "candidate_ranges": []},
}
check("zd5 turn-2 FIX: active_session=None with trip_planning NOT built "
      "(declined here, matching zd5) still gets the confirmed-dates "
      "{{DATES}} instruction",
      chat._DATES_PLACEHOLDER in chat._dates_truth_hint(_confirmed_state_no_active))
check("regression: lodging/car/trip_planning ACTIVE stay excluded even with "
      "the widened gate - they legitimately need real per-day literal dates",
      chat._dates_truth_hint(dict(_confirmed_state_no_active, active_session="lodging")) == ""
      and chat._dates_truth_hint(dict(_confirmed_state_no_active, active_session="car")) == ""
      and chat._dates_truth_hint(dict(_confirmed_state_no_active, active_session="trip_planning")) == "")

# Shaked's explicitly requested QA scenario: the final summary once the
# route is already built - the hint must NOT fire there, even with real
# confirmed dates in state, since it would reach into the itinerary's own
# per-day dates.
_route_built_state = {
    "active_session": None,
    "session_status": {"flights": "complete", "trip_planning": "complete", "lodging": "declined", "car": "declined"},
    "dates": {"departure": "2027-06-10", "return": "2027-06-14", "needs_confirmation": False, "candidate_ranges": []},
}
check("zd5 turn-2 FIX, correctly scoped: active_session=None but "
      "trip_planning is COMPLETE (route already built) -> no hint at all, "
      "exactly the scenario Shaked flagged in her rejection",
      chat._dates_truth_hint(_route_built_state) == "")
check("regression: active_session=None with no session_status/trip_planning "
      "key at all (treated as not complete) still gets the hint",
      chat._dates_truth_hint({"dates": {"departure": "2026-11-28", "return": "2026-12-05"}}) != "")
check("regression: active_session=None with nothing known at all still "
      "produces no hint (nothing to say)",
      chat._dates_truth_hint({}) == "")


# =====================================================================
# End-to-end: the exact zd5 shape - turn 1 (shift request, flight
# reactivated by mention, candidate created, Tinkerbell now correctly
# using {{DATE_OPTIONS}} per the hint) through to turn 2 ("כן", dates
# committed, flights closes again) - a full chat_clean() round trip via
# whatsapp_bridge.ariella_turn, mocking only the model calls.
# =====================================================================
m_zd5 = _make_member("qa-run9-zd5@example.com")
post_summary_state = {
    "destination": {"places": ["טורינו"], "mode": "specific", "status": "known"},
    "destination_airports": ["TRN"],
    "travelers": {"adults": 2},
    "dates": {"departure": "2027-06-10", "return": "2027-06-14", "needs_confirmation": False, "candidate_ranges": []},
    "requested_services": ["flights"],
    "session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
    "active_session": None,
    "ready_for_summary": True,
    "trip_type": "regular",
    "departure_airport": "TLV",
    "budget_per_person": {"amount": 2000, "currency": "ILS"},
    "flight": {"baggage": ["checked_bag"], "connection_preference": "no_preference"},
}
database.save_ariella_conversation(m_zd5, [
    {"role": "user", "content": "טורינו, 10-14 ביוני 2027, זוג, מזוודה"},
    {"role": "assistant", "content": "מאשרת שהכל סגור! חופשה נעימה! טורינו, 10-14 ביוני 2027."},
], dict(post_summary_state))


def _fake_turn1(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None,
            "relative_date_hint": {
                "weekday_start": None, "weekday_end": None, "month_name": None, "month_relative": None,
                "part_of_month": None, "duration_days": None, "shift_days": 1,
            },
            "relative_date_hint_evidence": "אפשר לדחות את הטיסה ביום אחד?",
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        # Now correctly steered by _dates_truth_hint - uses the real
        # placeholder instead of inventing her own open question.
        return "בטח, מצאתי אפשרות חדשה: " + chat._DATE_OPTIONS_PLACEHOLDER + " מתאים?"
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_turn1):
    reply1 = whatsapp_bridge.ariella_turn(m_zd5, "אפשר לדחות את הטיסה ביום אחד?")
state_after_turn1 = (database.load_ariella_conversation(m_zd5) or {}).get("trip_state") or {}
check("end-to-end turn 1: a real pending candidate was created and saved",
      bool((state_after_turn1.get("dates") or {}).get("candidate_ranges"))
      and (state_after_turn1.get("dates") or {}).get("needs_confirmation") is True)
check("end-to-end turn 1 FIX: the final reply shows the real candidate date "
      "(placeholder rendered), not a blind 'when would you like to "
      "depart/return' fallback",
      "11.06.2027" in reply1
      and "מתי תרצי לצאת ולחזור" not in reply1 and "מתי תרצה לצאת ולחזור" not in reply1)


def _fake_turn2(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None,
            "relative_date_hint": None, "relative_date_hint_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "תשובה לדוגמה."
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_turn2):
    # "כן" confirms the single pending candidate.
    reply2 = whatsapp_bridge.ariella_turn(m_zd5, "כן")
state_after_turn2 = (database.load_ariella_conversation(m_zd5) or {}).get("trip_state") or {}
check("end-to-end turn 2: 'כן' commits the candidate to real confirmed "
      "dates, needs_confirmation back to False",
      (state_after_turn2.get("dates") or {}).get("needs_confirmation") is False
      and (state_after_turn2.get("dates") or {}).get("departure") is not None)
check("end-to-end turn 2: flights closes back to complete, active_session "
      "back to None - the exact same-turn reopen-then-reclose",
      (state_after_turn2.get("session_status") or {}).get("flights") == "complete"
      and state_after_turn2.get("active_session") is None)


if FAILED:
    print(f"\n{len(FAILED)} CHECK(S) FAILED:")
    for name in FAILED:
        print(f"  - {name}")
    sys.exit(1)
print("\nALL RUN-9 ZD5 POST-SUMMARY-SHIFT-REPLY TESTS PASSED")
