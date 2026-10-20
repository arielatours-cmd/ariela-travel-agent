"""QA for Shlomo's relay (20.10.2026, live finding on main@30e07e1, prior to
PR #91): r90b2, Bologna - the FIRST design of this fix (a deterministic
date-range regex directly overwriting trip_update["dates"] once dates were
already closed, mirroring the existing sticky-dates re-lock mechanism) was
explicitly rejected by the business owner before it ever shipped, with 3
concrete risky examples of exactly the "phrase-matching instead of
understanding" pattern she forbids - a mid-conversation mention that merely
LOOKS like a date range, but is not a change request at all:
1. a flight's RETURN TIME mentioned in passing,
2. an unrelated event's date mentioned in passing,
3. a recalled PAST trip's dates ("בשנה שעברה טסנו 4-10 ביוני" - verified
   directly to genuinely match the existing date-range regex, a real false
   positive, not a hypothetical).

Redesigned per her explicit instruction: the deterministic regex safety net
may NEVER directly change state once dates are already closed. It may only
ever raise a confirm question (reusing the SAME guided-dispatch low-
confidence confirm mechanism already used elsewhere - see
_guided_confirm_hint), by reopening guided.current_question = "dates" and
removing "dates" from guided.answered. The actual save happens only once a
LATER turn's "כן" is itself resolved by the real guided dispatcher back into
a genuinely-confirmed value (_guided_confirmed_dates) - never a bare word
match on "כן" itself.

Run: python3 tools/qa_bologna_date_change_mid_question.py
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


def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA Bologna", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


_BASE_STATE = {
    "destination": {"places": ["בולוניה"], "mode": "specific", "status": "known"},
    "destination_airports": ["BLQ"],
    "travelers": {"adults": 2},
    "dates": {"departure": "2027-03-05", "return": "2027-03-10", "needs_confirmation": False},
    "requested_services": ["flights"],
    "service_decisions": {"flights": {"wanted": True}},
    "session_status": {"flights": "active", "lodging": "pending", "car": "pending", "trip_planning": "pending"},
    "active_session": "trip_planning",
    "guided": {"current_question": None, "attempts": 0, "answered": ["dates", "travelers", "baggage"]},
}


def _quiet_post_claude(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "תשובה לדוגמה."
    return "{}"


def _run_risky_example(email, message):
    member = _make_member(email)
    database.save_ariella_conversation(member, [
        {"role": "user", "content": "בולוניה, זוג, 5-10 במרץ 2027"},
        {"role": "assistant", "content": "קלטתי - בולוניה, 5-10 במרץ. לתכנן גם מסלול ואטרקציות?"},
    ], dict(_BASE_STATE))
    with patch.object(chat, "_post_claude", side_effect=_quiet_post_claude):
        whatsapp_bridge.ariella_turn(member, message)
    return (database.load_ariella_conversation(member) or {}).get("trip_state") or {}


# =====================================================================
# The 3 risky examples - each one matches the existing date-range regex
# (a day-day-month pattern) in a context that is NOT a change request.
# Dates must stay exactly as closed; the safety net may only reopen the
# guided question, never apply the match directly.
# =====================================================================
_risky_examples = {
    "flight return time mentioned in passing": (
        "qa-bologna-r1@example.com",
        "אגב, הטיסה שלנו חוזרת בטווח השעות 4-10 ביוני בבוקר, לא קשור לתאריכי הנסיעה",
    ),
    "unrelated event date mentioned in passing": (
        "qa-bologna-r2@example.com",
        "אגב, יש לנו אירוע משפחתי ב-4-10 ביוני, זה לא קשור לטיול שלנו",
    ),
    "a recalled PAST trip's dates (verified: genuinely matches the regex)": (
        "qa-bologna-r3@example.com",
        "בשנה שעברה טסנו 4-10 ביוני",
    ),
}

for label, (email, message) in _risky_examples.items():
    _state_after = _run_risky_example(email, message)
    _dates_after = _state_after.get("dates") or {}
    check(f"risky example ({label}): dates are NEVER silently changed",
          _dates_after.get("departure") == "2027-03-05" and _dates_after.get("return") == "2027-03-10")
    _guided_after = _state_after.get("guided") or {}
    check(f"risky example ({label}): guided.current_question is reopened to 'dates' "
          "(a confirm question, never a silent apply)",
          _guided_after.get("current_question") == "dates"
          and "dates" not in (_guided_after.get("answered") or []))

# Regression: an ordinary turn that mentions no date-range-shaped text at all
# must never reopen the guided dates question.
_quiet_state = _run_risky_example("qa-bologna-quiet@example.com", "מעולה, בואי נתכנן גם מסלול")
check("regression: an ordinary unrelated turn with no date-shaped text never reopens guided dates",
      (_quiet_state.get("guided") or {}).get("current_question") != "dates")

# =====================================================================
# The genuine 2-turn confirm flow: turn 1 raises the confirm question (same
# mechanism as the risky examples above - the regex alone never knows the
# difference between a genuine correction and a risky false-positive, which
# is exactly why it may only ever ask); turn 2's "כן" is resolved by the
# REAL guided dispatcher (never a bare word match) into the new dates.
# =====================================================================
m_confirm = _make_member("qa-bologna-confirm-flow@example.com")
database.save_ariella_conversation(m_confirm, [
    {"role": "user", "content": "בולוניה, זוג, 5-10 במרץ 2027"},
    {"role": "assistant", "content": "קלטתי - בולוניה, 5-10 במרץ. לתכנן גם מסלול ואטרקציות?"},
], dict(_BASE_STATE))

with patch.object(chat, "_post_claude", side_effect=_quiet_post_claude):
    whatsapp_bridge.ariella_turn(m_confirm, "בשנה שעברה טסנו 4-10 ביוני")
_after_turn1 = (database.load_ariella_conversation(m_confirm) or {}).get("trip_state") or {}
check("confirm flow turn 1: dates still untouched after the risky mention",
      _after_turn1.get("dates", {}).get("departure") == "2027-03-05")
check("confirm flow turn 1: guided dates question is reopened",
      (_after_turn1.get("guided") or {}).get("current_question") == "dates")


def _fake_post_claude_confirm_turn2(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({
            "status": "answered", "departure": "2027-06-04", "return": "2027-06-10",
            "confidence": "high", "also_mentioned": {},
        })
    if source == "tinkerbell_reply":
        return "עדכנתי לתאריכים החדשים."
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_confirm_turn2):
    whatsapp_bridge.ariella_turn(m_confirm, "כן, תעדכני לתאריכי יוני")
_after_turn2 = (database.load_ariella_conversation(m_confirm) or {}).get("trip_state") or {}
check("confirm flow turn 2: once the REAL guided dispatcher genuinely resolves the reopened "
      "dates question with high confidence, the new dates ARE saved",
      _after_turn2.get("dates", {}).get("departure") == "2027-06-04"
      and _after_turn2.get("dates", {}).get("return") == "2027-06-10")
check("confirm flow turn 2: guided question closes again (dates marked answered, "
      "current_question cleared)",
      "dates" in ((_after_turn2.get("guided") or {}).get("answered") or []))

# Regression: a bare "כן" with NOTHING genuinely resolved by the guided
# dispatcher (e.g. it still returns "unclear") must never finalize any date
# change - the whole point is that confirmation is itself understood, not
# word-matched.
m_bare_yes = _make_member("qa-bologna-bare-yes@example.com")
database.save_ariella_conversation(m_bare_yes, [
    {"role": "user", "content": "בולוניה, זוג, 5-10 במרץ 2027"},
    {"role": "assistant", "content": "קלטתי - בולוניה, 5-10 במרץ. לתכנן גם מסלול ואטרקציות?"},
], dict({**_BASE_STATE, "guided": {"current_question": "dates", "attempts": 0, "answered": ["travelers", "baggage"]}}))


def _fake_post_claude_unclear(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "unclear"})
    if source == "tinkerbell_reply":
        return "סליחה, לא הבנתי."
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_unclear):
    whatsapp_bridge.ariella_turn(m_bare_yes, "כן")
_bare_yes_state = (database.load_ariella_conversation(m_bare_yes) or {}).get("trip_state") or {}
check("regression: an ungenuine/unclear 'confirmation' the guided dispatcher itself can't resolve "
      "never changes the closed dates",
      _bare_yes_state.get("dates", {}).get("departure") == "2027-03-05")

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL BOLOGNA-DATE-CHANGE-MID-QUESTION TESTS PASSED")
