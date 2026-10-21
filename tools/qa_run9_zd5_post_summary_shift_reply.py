"""QA for Shlomo's relay (21.10.2026) of Shaked's run-9 live diagnostic repro
zd5 on c8ef25f ("לדחות ביום" - postpone by a day - after the final summary):

"לראשונה נוצר candidate 13.05–17.05 עם needs_confirmation=True, ואחרי 'כן'
הוא נשמר. ✅ אבל התשובות לא תאמו את ה-state:
- תור 1: 'מתי תרצי לצאת ולחזור?', בלי להציג את ההצעה. ב-missing_required
  היה 'dates'.
- תור 2: אחרי שה-state כבר נשמר, היא ענתה 'תוכלי לציין לי את התאריכים
  המדויקים...'."

Both turns are REPLY/STATE mismatches - the SAVE worked correctly both
times (confirmed directly in the live report), only the text shown to the
customer was wrong, in each turn for a different root cause:

TURN 1 root cause (confirmed by direct code reading + debug repro): the
customer's own message names "הטיסה" ("postpone THE FLIGHT"), which
_explicit_service_request's "go back and change the flight" mechanism
reads as a fresh request the instant nothing else is "in progress"
(post-summary, everything complete/declined) - reactivating session_
status.flights to "active" and active_session to "flights" for this one
turn, with NO request-cue word required (in_progress was False). The
shift_days mechanism then creates a real pending candidate this same
turn (dates.needs_confirmation=True, candidate_ranges=[label]) - but
_required_state_gaps treats ANY needs_confirmation=True exactly like "no
dates known at all", so "dates" lands in missing_required/gaps either way,
and _flight_gap_question's own "dates" branch returned the same blind
"מתי תרצה/י לצאת ולחזור?" fallback regardless, discarding the real
candidate sitting right there in state.

Fix: _flight_gap_question's "dates" branch now checks for a pending
candidate first and builds the real confirmation question directly from
it (the same " או " join _render_date_placeholders itself uses for
{{DATE_OPTIONS}} - this fixed-text path never goes through that
substitution, so the real text must be built here instead).

TURN 2 root cause (confirmed by debug repro): "כן" resolves the candidate
via _accept_single_proposed_date_range - the dates ARE correctly
committed. But _advance_sessions can close "flights" right back to
"complete" (active_session -> None) WITHIN THIS SAME TURN once dates stop
needing confirmation, and _dates_truth_hint - until now - returned ""
the instant active_session wasn't literally "flights", leaving Tinkerbell
with NO instruction at all about dates that had just this turn changed
and saved, free to ask for "the exact dates" as if nothing had happened.

Fix: _dates_truth_hint now also fires when active_session is None (no
active domain this turn at all), not only "flights" - still excluded for
lodging/car/trip_planning, which legitimately need real per-day literal
dates of their own.

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
# Direct unit coverage: _flight_gap_question's "dates" branch.
# =====================================================================
_pending_state = {
    "dates": {
        "needs_confirmation": True,
        "candidate_ranges": ["יום חמישי 11.06.2027–יום שני 15.06.2027"],
    },
    "user_gender": None,
}
_gap_reply = chat._flight_gap_question(["dates"], _pending_state)
check("zd5 turn-1 FIX: a pending single candidate produces the real "
      "confirmation question naming that exact candidate",
      "11.06.2027" in _gap_reply and "15.06.2027" in _gap_reply)
check("zd5 turn-1 FIX: the blind 'when would you like to depart/return' "
      "fallback text is NOT used while a candidate is pending",
      "מתי תרצי לצאת ולחזור" not in _gap_reply and "מתי תרצה לצאת ולחזור" not in _gap_reply)

_pending_two_state = {
    "dates": {
        "needs_confirmation": True,
        "candidate_ranges": [
            "יום חמישי 11.06.2027–יום שני 15.06.2027",
            "יום חמישי 18.06.2027–יום שני 22.06.2027",
        ],
    },
}
_gap_reply_two = chat._flight_gap_question(["dates"], _pending_two_state)
check("regression: two pending candidates are BOTH named, joined by 'או' "
      "(matches _render_date_placeholders' own DATE_OPTIONS join exactly)",
      "11.06.2027" in _gap_reply_two and "18.06.2027" in _gap_reply_two
      and " או " in _gap_reply_two)

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
# Direct unit coverage: _dates_truth_hint's widened gate (turn 2).
# =====================================================================
_confirmed_state_no_active = {"dates": {"departure": "2026-11-28", "return": "2026-12-05"}}
check("zd5 turn-2 FIX: active_session=None (closed again the same turn dates "
      "were confirmed) still gets the confirmed-dates {{DATES}} instruction",
      chat._DATES_PLACEHOLDER in chat._dates_truth_hint(_confirmed_state_no_active))
check("regression: lodging/car/trip_planning stay excluded even with the "
      "widened gate - they legitimately need real per-day literal dates",
      chat._dates_truth_hint(dict(_confirmed_state_no_active, active_session="lodging")) == ""
      and chat._dates_truth_hint(dict(_confirmed_state_no_active, active_session="car")) == ""
      and chat._dates_truth_hint(dict(_confirmed_state_no_active, active_session="trip_planning")) == "")
check("regression: active_session=None with nothing known at all still "
      "produces no hint (nothing to say)",
      chat._dates_truth_hint({}) == "")


# =====================================================================
# End-to-end: the exact zd5 shape - turn 1 (shift request, flight
# reactivated by mention, candidate created) through to turn 2 ("כן",
# dates committed, flights closes again) - a full chat_clean() round trip
# via whatsapp_bridge.ariella_turn, mocking only the model calls.
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
        # The exact live bug: the blind open question, ignoring the
        # candidate - stands in for what a real, unguided model call
        # produced live. _flight_gap_question's own fixed fallback (not
        # this mocked text) is what the fix actually changes; this mock
        # exists only to drive the pipeline through to where that fallback
        # gets consulted via the premature-gap-question/approval paths.
        return "מתי תרצי לצאת ולחזור?"
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_turn1):
    reply1 = whatsapp_bridge.ariella_turn(m_zd5, "אפשר לדחות את הטיסה ביום אחד?")
state_after_turn1 = (database.load_ariella_conversation(m_zd5) or {}).get("trip_state") or {}
check("end-to-end turn 1: a real pending candidate was created and saved "
      "(the live report's own confirmed-correct part)",
      bool((state_after_turn1.get("dates") or {}).get("candidate_ranges"))
      and (state_after_turn1.get("dates") or {}).get("needs_confirmation") is True)

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
      "dates, needs_confirmation back to False (the live report's own "
      "confirmed-correct part)",
      (state_after_turn2.get("dates") or {}).get("needs_confirmation") is False
      and (state_after_turn2.get("dates") or {}).get("departure") is not None)
check("end-to-end turn 2: flights closes back to complete, active_session "
      "back to None - the exact same-turn reopen-then-reclose that left "
      "_dates_truth_hint silent before this fix",
      (state_after_turn2.get("session_status") or {}).get("flights") == "complete"
      and state_after_turn2.get("active_session") is None)


if FAILED:
    print(f"\n{len(FAILED)} CHECK(S) FAILED:")
    for name in FAILED:
        print(f"  - {name}")
    sys.exit(1)
print("\nALL RUN-9 ZD5 POST-SUMMARY-SHIFT-REPLY TESTS PASSED")
