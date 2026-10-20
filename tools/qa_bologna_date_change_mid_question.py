"""QA for Shlomo's relay (20.10.2026, live finding on main@30e07e1, prior to
PR #91): r90b2, Bologna - the FIRST design of this fix (a deterministic
date-range regex directly overwriting trip_update["dates"] once dates were
already closed, mirroring the existing sticky-dates re-lock mechanism) was
explicitly rejected by the business owner before it ever shipped, with 3
concrete risky examples of exactly the "phrase-matching instead of
understanding" pattern she forbids - a mid-conversation mention that merely
LOOKS like a date range, but is not a change request at all.

The SECOND design (merged into PR #94 before Shaked's review): the regex
could no longer silently apply a match, but it still DIRECTLY TRIGGERED a
confirm question (reopening guided.current_question = "dates") on any
date-shaped text, with no understanding of intent at all. Shaked's
regression review found this STILL misfired - needlessly interrupting the
conversation with "did you mean to change the dates?" - on messages that
are clearly not a change request at all, including two the business owner
never even tested the first time:
1. a flight's RETURN TIME mentioned in passing,
2. a recalled PAST trip's dates ("בשנה שעברה טסנו 4-10 ביוני"),
3. someone ELSE's dates, explicitly NOT a change ("החברים שלנו טסים 4-10
   ביוני, אנחנו נשארים בתאריכים שלנו"),
4. an open comparison question ("מה דעתך, 4-10 ביוני עדיף על 3-9?").

Fixed for real this time: the regex trigger is REMOVED ENTIRELY. The only
mechanism left is the pre-existing evidence-gated model path - a genuine
date-change request is detected ONLY when the extractor itself (the model)
returns a differing dates.departure/return in trip_update AND a dates_
evidence verbatim quote from the customer's current message
(_value_has_verbatim_evidence) - the exact same mechanism EXTRACTOR_SYSTEM
already instructs the model to use for a change phrased as a question mid
another topic (see its dates_evidence section). No regex of any kind
decides this any more, and nothing interrupts the conversation with an
unwanted confirm question just because some text happens to look
date-shaped.

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
    # Simulates the extractor genuinely seeing nothing date-related this
    # turn - no trip_update.dates, no dates_evidence - exactly what a
    # correctly-behaving model should return for text that isn't a change
    # request at all, regardless of how date-shaped it looks.
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
# Four risky examples, each date-shaped text that is genuinely NOT a
# change request. With the regex trigger removed entirely, none of these
# may change the dates OR interrupt the conversation with a confirm
# question any more - the model (here, correctly, finding nothing) is the
# only thing deciding, so there is nothing left here to even raise.
# =====================================================================
_risky_examples = {
    "flight return time mentioned in passing": (
        "qa-bologna-r1@example.com",
        "אגב, הטיסה שלנו חוזרת בטווח השעות 4-10 ביוני בבוקר, לא קשור לתאריכי הנסיעה",
    ),
    "a recalled PAST trip's dates": (
        "qa-bologna-r3@example.com",
        "בשנה שעברה טסנו 4-10 ביוני",
    ),
    "someone else's dates, explicitly not a change": (
        "qa-bologna-r4@example.com",
        "החברים שלנו טסים 4-10 ביוני, אנחנו נשארים בתאריכים שלנו",
    ),
    "an open comparison question": (
        "qa-bologna-r5@example.com",
        "מה דעתך, 4-10 ביוני עדיף על 3-9?",
    ),
}

for label, (email, message) in _risky_examples.items():
    _state_after = _run_risky_example(email, message)
    _dates_after = _state_after.get("dates") or {}
    check(f"risky example ({label}): dates are NEVER silently changed",
          _dates_after.get("departure") == "2027-03-05" and _dates_after.get("return") == "2027-03-10")
    _guided_after = _state_after.get("guided") or {}
    check(f"risky example ({label}): no regex trigger of any kind reopens the "
          "guided dates question any more - nothing here is even a candidate "
          "for interrupting the conversation",
          _guided_after.get("current_question") != "dates"
          and "dates" in (_guided_after.get("answered") or []))

# Regression: an ordinary turn that mentions no date-range-shaped text at all
# must never reopen the guided dates question either.
_quiet_state = _run_risky_example("qa-bologna-quiet@example.com", "מעולה, בואי נתכנן גם מסלול")
check("regression: an ordinary unrelated turn with no date-shaped text never reopens guided dates",
      (_quiet_state.get("guided") or {}).get("current_question") != "dates")

# =====================================================================
# The genuine case this fix must still handle: a date-change request
# phrased as a question, embedded mid another topic (the ORIGINAL Bologna
# live finding) - detected ONLY via the model's own extractor output plus a
# verbatim dates_evidence quote, in a SINGLE turn, never a regex and never a
# two-turn confirm dance.
# =====================================================================
def _fake_post_claude_genuine_change(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {"dates": {"departure": "2027-06-04", "return": "2027-06-10"}},
            "restart_request": False, "restart_evidence": None,
            "dates_evidence": "4 עד 10 ביוני",
            "destination_evidence": None, "trip_type_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "בטח, אשנה את התאריכים ל-4 עד 10 ביוני - ולגבי הקצב, חשוב לכם שהוא יהיה רגוע?"
    return "{}"


m_genuine = _make_member("qa-bologna-genuine-change@example.com")
database.save_ariella_conversation(m_genuine, [
    {"role": "user", "content": "בולוניה, זוג, 5-10 במרץ 2027"},
    {"role": "assistant", "content": "קלטתי - בולוניה, 5-10 במרץ. לתכנן גם מסלול ואטרקציות?"},
], dict(_BASE_STATE))

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_genuine_change):
    whatsapp_bridge.ariella_turn(m_genuine, "רגע, אפשר לשנות ל-4 עד 10 ביוני? ולגבי הקצב - רגוע או פעיל?")
_after_genuine = (database.load_ariella_conversation(m_genuine) or {}).get("trip_state") or {}
check("the ORIGINAL Bologna live finding (a date-change request phrased as "
      "a question, mid another topic): the model's own extractor output "
      "plus a verbatim dates_evidence quote is enough to save the new "
      "dates in ONE turn - no regex, no confirm round-trip needed",
      _after_genuine.get("dates", {}).get("departure") == "2027-06-04"
      and _after_genuine.get("dates", {}).get("return") == "2027-06-10")

# Regression: the extractor claiming a differing date range WITHOUT a
# genuine verbatim quote behind it must never be trusted either - evidence
# is still required, this just removes the SEPARATE regex path, it doesn't
# loosen the evidence gate on the model path.
def _fake_post_claude_unverified_evidence(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {"dates": {"departure": "2027-06-04", "return": "2027-06-10"}},
            "restart_request": False, "restart_evidence": None,
            "dates_evidence": "משהו שלא נאמר בהודעה בכלל",
            "destination_evidence": None, "trip_type_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "תשובה לדוגמה."
    return "{}"


m_unverified = _make_member("qa-bologna-unverified-evidence@example.com")
database.save_ariella_conversation(m_unverified, [
    {"role": "user", "content": "בולוניה, זוג, 5-10 במרץ 2027"},
    {"role": "assistant", "content": "קלטתי - בולוניה, 5-10 במרץ. לתכנן גם מסלול ואטרקציות?"},
], dict(_BASE_STATE))

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_unverified_evidence):
    whatsapp_bridge.ariella_turn(m_unverified, "מעולה, בואי נתכנן מסלול")
_after_unverified = (database.load_ariella_conversation(m_unverified) or {}).get("trip_state") or {}
check("regression: an extractor-claimed date change whose dates_evidence "
      "quote does NOT actually appear in the customer's message is still "
      "rejected - removing the regex path never loosened the evidence gate",
      _after_unverified.get("dates", {}).get("departure") == "2027-03-05")

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL BOLOGNA-DATE-CHANGE-MID-QUESTION TESTS PASSED")
