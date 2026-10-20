"""QA for Shaked's second PR #85 review (18.10.2026): the first version of
the _reset_intent removal (2726642) replaced the phrase list with a
DEDICATED `_interpret_pending_choice` classifier call, made unconditionally
whenever `_has_vacation_progress(trip_state)` is true - i.e. on almost
every turn once a vacation has any real progress. That doubled the model
calls per turn (the normal state_extractor call always ran too), on turns
Shaked reported already running close to 28 seconds against a 30-second
cutoff.

The fix: restart_request/restart_evidence now ride the SAME single
state_extractor call that already runs for most turns (siblings of
trip_update in EXTRACTOR_SYSTEM's own JSON output - see
_parse_restart_signal in ariella_chat_clean.py), and the whole gate is
checked right after that one call returns, before the merge. The cheap,
free checks (reset_pending, own_pending_question) are evaluated as part of
the same gate, so a turn where they already rule out a restart pays
nothing extra either way - the extractor call was always going to run.

This file asserts the fix by wrapping `_interpret_pending_choice` itself
(the specific function the first fix called an extra time for this gate)
with a call counter, rather than counting every source="classifier" call
generically - several OTHER, unrelated mechanisms (e.g. guided-answer
interpretation) legitimately also use source="classifier" and must not be
mistaken for this one:
1. An ordinary continuing turn with real vacation progress never calls
   _interpret_pending_choice at all for this gate, and makes exactly one
   state_extractor call (no duplicate extraction).
2. A turn whose message DOES trigger the restart gate also never calls
   _interpret_pending_choice, costs only ONE model call total (the
   extractor) - the gate returns immediately with a literal reply, so it
   is cheaper than an ordinary turn, never doubled.

Run: python3 tools/qa_restart_signal_no_extra_model_call.py
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
            ("QA No Extra Call", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def _customer_text(message):
    return str(message or "").split("תשובת הלקוח:", 1)[-1].strip()


_RESTART_PHRASES = ("טיול חדש", "חופשה חדשה", "טיול אחר", "חדש ונפרד")

prague_state = {
    "destination": {"places": ["פראג"], "mode": "specific", "status": "known"},
    "destination_airports": ["PRG"],
    "travelers": {"adults": 2},
    "session_status": {"flights": "active", "lodging": "pending", "car": "pending", "trip_planning": "pending"},
    "active_session": "flights",
    "guided": {"current_question": "baggage", "attempts": 0, "answered": ["dates", "travelers"]},
}


def _make_counting_post_claude(counts):
    def _fake(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
        counts[source] = counts.get(source, 0) + 1
        if source == "tinkerbell_reply":
            return "תשובה כלשהי."
        if source == "state_extractor":
            text = _customer_text(message)
            hit = next((p for p in _RESTART_PHRASES if p in text), None)
            if hit:
                return json.dumps({"trip_update": {}, "restart_request": True, "restart_evidence": hit})
            return "{}"
        # Any other source (e.g. the guided-answer interpreter, which also
        # legitimately uses source="classifier" for unrelated reasons) gets
        # a harmless default - this file is not testing those mechanisms.
        return "{}"
    return _fake


_original_interpret_pending_choice = chat._interpret_pending_choice


def _make_counting_interpret_pending_choice(counter):
    def _wrapped(*args, **kwargs):
        counter["calls"] += 1
        return _original_interpret_pending_choice(*args, **kwargs)
    return _wrapped


# =====================================================================
# 1. An ordinary continuing turn (no restart language at all) on a state
#    with real vacation progress: _interpret_pending_choice is never
#    called for this gate, and exactly one state_extractor call happens -
#    this gate adds nothing to the normal per-turn cost.
# =====================================================================
m_ok = _make_member("qa-no-extra-call-ordinary@example.com")
database.save_ariella_conversation(m_ok, [
    {"role": "user", "content": "פראג, זוג, ביולי"},
    {"role": "assistant", "content": "קלטתי - פראג. איזו כבודה תצטרכו?"},
], dict(prague_state))
counts_ok = {}
ipc_calls_ok = {"calls": 0}
with patch.object(chat, "_post_claude", side_effect=_make_counting_post_claude(counts_ok)), \
     patch.object(chat, "_interpret_pending_choice", side_effect=_make_counting_interpret_pending_choice(ipc_calls_ok)):
    whatsapp_bridge.ariella_turn(m_ok, "טרולי לכל אחד")
check("ordinary turn: exactly one state_extractor call (no duplicate extraction)",
      counts_ok.get("state_extractor") == 1)
check("ordinary turn: _interpret_pending_choice is never called - the dedicated restart classifier call is gone entirely",
      ipc_calls_ok["calls"] == 0)

# =====================================================================
# 2. A turn whose message DOES trigger the restart gate: only ONE model
#    call total - the gate returns immediately with a literal reply once
#    the single extractor call reports restart_request=true, never
#    reaching the tinkerbell_reply call, and never calling
#    _interpret_pending_choice either. Cheaper than an ordinary turn, not
#    doubled.
# =====================================================================
m_restart = _make_member("qa-no-extra-call-restart@example.com")
database.save_ariella_conversation(m_restart, [
    {"role": "user", "content": "פראג, זוג, ביולי"},
    {"role": "assistant", "content": "קלטתי - פראג. איזו כבודה תצטרכו?"},
], dict(prague_state))
counts_restart = {}
ipc_calls_restart = {"calls": 0}
with patch.object(chat, "_post_claude", side_effect=_make_counting_post_claude(counts_restart)), \
     patch.object(chat, "_interpret_pending_choice", side_effect=_make_counting_interpret_pending_choice(ipc_calls_restart)):
    reply_restart = whatsapp_bridge.ariella_turn(m_restart, "רגע, אני רוצה להתחיל טיול אחר")
state_restart = (database.load_ariella_conversation(m_restart) or {}).get("trip_state") or {}
check("precondition: the restart gate actually fired for this message",
      bool(state_restart.get("reset_pending")))
check("restart turn: _interpret_pending_choice is never called",
      ipc_calls_restart["calls"] == 0)
check("restart turn: only ONE model call total - the gate returns before ever reaching tinkerbell_reply",
      sum(counts_restart.values()) == 1)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL RESTART-SIGNAL-NO-EXTRA-MODEL-CALL TESTS PASSED")
