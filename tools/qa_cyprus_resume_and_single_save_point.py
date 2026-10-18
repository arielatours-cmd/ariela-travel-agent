"""QA for the urgent "Cyprus resume" bug (18.10.2026, business owner via
WhatsApp 07:29 "הי" -> Ariella kept re-offering a closed flights-only
Cyprus vacation and re-asking about direct flights; root-cause report:
qa/reports/2026-10-18-cyprus-resume.md, branch shaked @721ac8e). Shlomo's
instruction: one urgent PR, priority before continuing PR #83, covering:

(a) A service the customer already DECIDED on (declined, or complete) must
    never be treated as "missing" when Ariella is the one PROACTIVELY
    offering to continue a saved vacation on a bare "הי". Fixed with a new,
    separate check (_service_decided_on_trip) and a new exclude_decided
    parameter on _reopenable_trips, used only by _upcoming_vacations - an
    EXPLICIT "add lodging to my Cyprus trip" request still uses
    _service_missing_on_trip's own permissive check, unchanged, since
    asking for it now overrides an earlier decline.

(b) The continuity hint handed to Tinkerbell for each such vacation now
    states what's already CLOSED (flights, always, plus any declined/
    complete domain) - never just what's still open - and the general-
    greeting instruction now explicitly says to PROPOSE the open question
    and WAIT for the customer's answer, never continue planning on its
    own initiative before the customer picks.

(c) A trip where every remaining domain is already decided now never
    appears in _upcoming_vacations at all - falls out naturally from (a),
    since every one of the 3 per-service passes that build the result
    excludes it.

(d)/(5)/(6) The deeper root cause of why "כן" (after "למחוק את כל הפרטים
ולהתחיל חופשה חדשה מאפס?") landed on a stale, already-answered flight
question instead of actually resetting: _chat_clean_impl had ~10 different
`return jsonify(...)` branches - the reset gate's own question among them -
that never persisted the turn at all (no call to save_ariella_conversation
or _remember_turn_reset_trip). WhatsApp reloads the ENTIRE conversation
from the server on every single turn, so an unsaved gate question is
invisible to the very next turn: the "כן" that followed landed on the OLD,
still-saved state (history still ending in "...חשוב לך שתהיה ישירה?"),
got read as answering THAT stale question, and guided advanced straight to
baggage. Fixed with a single exit point: every success branch now returns
through a new _reply(payload) closure instead of calling jsonify directly,
and _reply is the ONLY place that persists a turn (re-reading the DB first,
matching _remember_turn_reset_trip's own now-removed pattern, so a
same-account concurrent request is appended after, never clobbered). No
branch saves on its own anymore - _remember_turn_reset_trip itself is
deleted as dead code.

Tests 1-7 below are unit/integration-level (direct function calls,
including a real DB fixture for the Cyprus trip). Test 8 is the full
end-to-end repro Shlomo explicitly asked for: through
whatsapp_bridge.ariella_turn itself, two real turns. The reset gate's
yes/no interpretation (turn 2, "כן") is still fully deterministic/regex-
based. The new-vacation language detector for turn 1 is NOT anymore: per
Shlomo's later follow-up (18.10, task/resume-live-reset-and-one-question),
_reset_intent's fixed phrase list was removed from this gate entirely -
only the model classifier (_interpret_pending_choice) decides now, per the
business owner's 18.10 directive. Turn 1 therefore patches _post_claude
for source="classifier" so the test does not depend on a real network call.

Run: python3 tools/qa_cyprus_resume_and_single_save_point.py
"""
import os
import sys
import json
import sqlite3
from datetime import datetime, timezone, timedelta

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
            ("QA Cyprus Resume", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def _make_trip(member_id, name, answers, dep, ret):
    with sqlite3.connect(DB) as conn:
        cur = conn.execute(
            "INSERT INTO trip_requests (member_id, request_name, travel_window, created_at, status, answers_json) VALUES(?,?,?,?,?,?)",
            (member_id, name, f"{dep} - {ret}", datetime.now(timezone.utc).isoformat(), "active", json.dumps(answers, ensure_ascii=False)),
        )
        return cur.lastrowid


# =====================================================================
# (a) _service_decided_on_trip: a separate check from _service_missing_
# on_trip, which never looks at the customer's own decision at all.
# =====================================================================
check("_service_decided_on_trip: True when _session_status marks the "
      "service declined",
      chat._service_decided_on_trip({"_session_status": {"lodging": "declined"}}, "lodging") is True)
check("_service_decided_on_trip: True when _session_status marks it complete",
      chat._service_decided_on_trip({"_session_status": {"car": "complete"}}, "car") is True)
check("_service_decided_on_trip: True when the saved _ariella_trip_state "
      "has service_decisions[service].wanted=False",
      chat._service_decided_on_trip(
          {"_ariella_trip_state": {"service_decisions": {"trip_planning": {"wanted": False}}}},
          "trip_planning",
      ) is True)
check("_service_decided_on_trip: False for a service that was simply "
      "never addressed at all (pending/absent)",
      chat._service_decided_on_trip({}, "lodging") is False
      and chat._service_decided_on_trip({"_session_status": {"lodging": "pending"}}, "lodging") is False)
check("regression: _service_missing_on_trip itself is completely "
      "unaffected (still the old permissive check, for explicit-add "
      "requests)",
      chat._service_missing_on_trip({"_session_status": {"lodging": "declined"}}, "lodging") is True)

# =====================================================================
# (a)/(c) Real DB fixture: the exact Cyprus shape (flights-only,
# lodging/car/trip_planning all declined) must never be proactively
# offered, and a trip with at least one genuinely open domain still is.
# =====================================================================
member_id = _make_member("qa-cyprus-resume@example.com")
future_dep = (datetime.now(timezone.utc) + timedelta(days=60)).date().isoformat()
future_ret = (datetime.now(timezone.utc) + timedelta(days=65)).date().isoformat()

cyprus_answers = {
    "origin_airports": ["TLV"], "destinations": "LCA",
    "departure_date": future_dep, "return_date": future_ret, "adults": 2,
    "_session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
}
cyprus_trip_id = _make_trip(member_id, "קפריסין", cyprus_answers, future_dep, future_ret)

check("(a) a fully-declined trip (Cyprus shape) is NEVER returned by "
      "_reopenable_trips when exclude_decided=True, for any of the 3 "
      "services",
      all(
          not any(t["id"] == cyprus_trip_id for t in chat._reopenable_trips(member_id, s, "", limit=20, exclude_decided=True))
          for s in ("lodging", "car", "trip_planning")
      ))
check("regression: the SAME fully-declined trip is still found when "
      "exclude_decided is left at its default False (an explicit "
      "'add lodging to Cyprus' request must keep working)",
      any(t["id"] == cyprus_trip_id for t in chat._reopenable_trips(member_id, "lodging", "", limit=20)))
check("(c) _upcoming_vacations is empty - the fully-declined Cyprus trip "
      "is never proactively offered on a bare greeting",
      chat._upcoming_vacations(member_id) == [])

# A SECOND trip for the same member, with a genuinely open domain (lodging
# still never searched) - must still be offered normally, listing what's
# closed (flights + the declined car/trip_planning) and what's open.
future_dep2 = (datetime.now(timezone.utc) + timedelta(days=90)).date().isoformat()
future_ret2 = (datetime.now(timezone.utc) + timedelta(days=97)).date().isoformat()
open_answers = {
    "origin_airports": ["TLV"], "destinations": "FCO",
    "departure_date": future_dep2, "return_date": future_ret2, "adults": 2,
    "_session_status": {"flights": "complete", "lodging": "active", "car": "declined", "trip_planning": "declined"},
}
open_trip_id = _make_trip(member_id, "רומא", open_answers, future_dep2, future_ret2)

upcoming = chat._upcoming_vacations(member_id)
check("(a)/(b) the Rome trip (lodging genuinely still open) IS offered, "
      "with 'missing' naming only lodging (not the already-declined "
      "car/trip_planning)",
      len(upcoming) == 1 and upcoming[0]["name"] == "רומא" and upcoming[0]["missing"] == ["לינה"])
check("(b) 'closed' lists flights plus every already-declined domain for "
      "that same trip",
      set(upcoming[0]["closed"]) == {"טיסות", "רכב שכור", "מסלול ואטרקציות"})

# =====================================================================
# (b) The continuity hint actually handed to Tinkerbell states what's
# closed and instructs her to propose-and-wait, not continue on her own.
# =====================================================================
captured = {}


def _capture_post_claude(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    captured["system_dynamic"] = system_dynamic
    return "בטח, להמשיך את החופשה לרומא או להתחיל חדשה?"


from unittest.mock import patch

state_no_destination = {
    "session_status": {"flights": "pending", "lodging": "pending", "car": "pending", "trip_planning": "pending"},
    "upcoming_vacations": upcoming,
}
with patch.object(chat, "_post_claude", _capture_post_claude):
    chat._call_tinkerbell("test-key", "claude-sonnet-5", [], "הי", state=state_no_destination)
hint_text = captured.get("system_dynamic") or ""
check("(b) the hint names what's already closed on the offered trip "
      "('כבר סגור')",
      "כבר סגור" in hint_text and "רכב" in hint_text and "מסלול" in hint_text)
check("(b) the hint explicitly instructs Tinkerbell to propose-and-WAIT, "
      "never continue planning before the customer answers",
      "חכי לתשובת הלקוח" in hint_text and "אל תמשיכי בתכנון בעצמך" in hint_text)
check("regression: the hint still tells her never to re-ask dates/"
      "travelers/anything already-closed",
      "לעולם אל תשאלי שוב" in hint_text)

# =====================================================================
# (d)/(5)/(6) Full end-to-end repro via whatsapp_bridge.ariella_turn,
# exactly as instructed - no mocked model call needed (every branch
# involved here is deterministic, long before any _post_claude call).
# =====================================================================
wa_member_id = _make_member("qa-cyprus-resume-wa@example.com")
database.clear_ariella_conversation(wa_member_id)

# Seed the exact pre-bug state: a stale guided.current_question left over
# from an earlier (closed) flights-only Cyprus conversation, mid-baggage-
# question - the same shape Shaked's own report reconstructed.
stale_state = {
    "destination": {"places": ["קפריסין"], "mode": "specific", "status": "known"},
    "destination_airports": ["LCA"],
    "dates": {"departure": future_dep, "return": future_ret},
    "travelers": {"adults": 2},
    "session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
    "active_session": None,
    "flight": {"connection_preference": "direct"},
    "guided": {"current_question": "baggage", "attempts": 1, "answered": ["lodging_type"]},
}
stale_history = [
    {"role": "user", "content": "רק טיסה לקפריסין, בלי לינה ורכב"},
    {"role": "assistant", "content": "קלטתי - רק טיסה. לגבי הטיסה - חשוב לך שתהיה ישירה?"},
]
database.save_ariella_conversation(wa_member_id, stale_history, stale_state)

def _fake_post_claude_classifier(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source != "classifier":
        return "{}"
    text = str(message or "").split("תשובת הלקוח:", 1)[-1].strip()
    if "question_kind=new_vacation" in str(message or "") and ("חדש" in text or "אחר" in text):
        return "NEW"
    return "UNCLEAR"


with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_classifier):
    turn1_reply = whatsapp_bridge.ariella_turn(wa_member_id, "כבר סגרנו את פרטי הטיסה. אני רוצה לתכנן טיול חדש")
check("turn 1: the reply is genuinely the reset gate question",
      "למחוק" in turn1_reply and "מאפס" in turn1_reply)

after_turn1 = database.load_ariella_conversation(wa_member_id)
check("turn 1 IS persisted server-side (the single-save-point fix): "
      "reset_pending=True actually reached the DB, and the gate question "
      "itself is in the saved history",
      bool((after_turn1 or {}).get("trip_state", {}).get("reset_pending"))
      and after_turn1["history"][-1]["content"] == turn1_reply
      and after_turn1["history"][-2]["content"] == "כבר סגרנו את פרטי הטיסה. אני רוצה לתכנן טיול חדש")

turn2_reply = whatsapp_bridge.ariella_turn(wa_member_id, "כן")
after_turn2 = database.load_ariella_conversation(wa_member_id)
final_state = (after_turn2 or {}).get("trip_state") or {}
check("turn 2 ('כן'): the reply is the fresh-start message, NOT a repeat "
      "of the flight/baggage question from the stale Cyprus conversation "
      "(the exact live bug - reproduced here and now fixed)",
      "חדשה" in turn2_reply and "כבודה" not in turn2_reply and "ישירה" not in turn2_reply)
check("turn 2: the new trip_update has no leftover 'guided' state at all "
      "- a full reset must never carry a stale current_question/attempts "
      "forward",
      "guided" not in final_state)
check("turn 2: the new trip_update has no leftover Cyprus destination/"
      "flight data either - a genuine full reset, not a patch",
      not ((final_state.get("destination") or {}).get("places"))
      and not final_state.get("flight"))
check("turn 2 is ALSO persisted (both turns go through the same single "
      "exit point)",
      after_turn2["history"][-2]["content"] == "כן"
      and after_turn2["history"][-1]["content"] == turn2_reply)

if FAILED:
    print(f"\nFAILED ({len(FAILED)}): {FAILED}")
    sys.exit(1)
print("\nALL CYPRUS-RESUME / SINGLE-SAVE-POINT TESTS PASSED")
