"""QA for run-11's central finding #1 (Shaked/Shlomo, 22.10.2026,
qa/reports/2026-10-22-stage1-live-run11.md, branch shaked 25c8c91) - 1/5
live conversations passed, 4 of them (Bari/Valencia/Bordeaux/Rovinj) never
asked the accessibility question at all:

Root cause 1 (turns 0-4, every failing case): when dates AND travelers both
arrive in the customer's very first message, the general extractor writes
them into trip_update BEFORE _handle_guided_extraction_turn ever runs. Its
own top-of-function loop immediately marks both "answered" and advances
current_question straight to "accessibility" - then calls
_guided_extract_answer("accessibility", ...) against that SAME first
message, which (correctly) classifies as status="other_topic" since the
message never mentioned accessibility at all. The "other_topic" handler
then looks for some OTHER still-open guided field the message might
actually be about (the redirect mechanism PR #116/#137 established) - but
finds none, since dates/travelers were already consumed moments earlier in
the very same call. With nothing to redirect to, the old code unconditionally
returned dynamic_hint=None - and the caller POPS trip_update["_guided_ask_
hint"] entirely whenever the hint is falsy, leaving Tinkerbell with zero
steering this turn, free to ask about baggage/budget/anything else instead.

Root cause 2 (case A, turns 5-10): once every one of the four domains
(flights/lodging/car/trip_planning) reads complete/declined, two separate
state-only checks short-circuited around the guided dispatcher entirely -
(a) the dispatcher's own early-exit gate stopped calling it at all ("nothing
left to guide" once every domain is decided - true for domain-scoped facts,
false for a universal cross-domain field like accessibility that lives
outside all four), and (b) _advance_sessions's own ready_for_summary read
True from session_status alone, with no check that every genuinely open
guided field (accessibility first) had actually been asked. Together these
let the one real combined-approval moment (and the "never let a reply skip
the final summary" safety net right next to it) win over an accessibility
question nobody had asked yet - exactly the live symptom: a hint reworded
and left in place turns 5-10, yet the final מאשרת summary went out anyway.

Fix (state only, never a scan of Tinkerbell's own reply text - per the
business owner's standing rule):

1. _handle_guided_extraction_turn's "other_topic, nothing to redirect to"
   fallback always asks the genuinely-still-open current_question's own
   hint now, instead of returning None.
2. New _guided_incomplete_fields(state): every guided-covered, applicable,
   not-yet-answered field right now - the one shared check that:
   (a) widens the dispatcher's own early-exit gate (_all_domains_already_
       decided) to keep running while such a field remains open, even once
       every domain itself is complete/declined;
   (b) widens _advance_sessions's ready_for_summary the same way - the one
       real approval moment now requires every covered field resolved, not
       just the four domains;
   (c) backstops a premature מאשרת reply inside the same safety net that
       already retries Tinkerbell for an open domain gap - when nothing
       else is open but a guided field still is, the retry forces that
       field's own hint as the very last thing Tinkerbell sees before
       composing again.

Run: python3 tools/qa_run11_accessibility_hint_gate.py
"""
import os
import sys
import json
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

import ariella_chat_clean as chat
import app as app_module
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash
import sqlite3

DB = database.DB_PATH
client = app_module.app.test_client()

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
            ("QA run11 acc", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def _post(message, history, trip_state, member_id):
    with client.session_transaction() as sess:
        sess["member_id"] = member_id
    r = client.post("/api/ariella/chat-clean", json={
        "message": message, "history": history, "trip_state": trip_state,
    })
    return r.get_json()


# =====================================================================
# 1. Direct unit coverage of _handle_guided_extraction_turn's fixed
#    fallback: Bari-shaped turn 0 - dates+travelers already resolved THIS
#    turn (as the general extractor would have written them before this
#    function runs), current_question freshly advances to accessibility,
#    the message itself never mentions it -> other_topic, no redirect
#    candidate left (dates/travelers just consumed) -> must still ask
#    accessibility, never return no hint at all.
# =====================================================================
with patch.object(chat, "_post_claude", return_value=json.dumps(
    {"status": "other_topic", "field": None, "evidence": None}
)):
    trip_update_bari = {
        "destination": {"places": ["בארי"], "mode": "specific", "status": "known"},
        "requested_services": ["flights"],
        "dates": {"departure": "2027-04-10", "return": "2027-04-15"},
        "travelers": {"adults": 2},
        "flight": {"baggage": []},
    }
    result_bari = chat._handle_guided_extraction_turn(
        "fakekey", "fake-model", "טסים לבארי שניים, ה-10 עד ה-15 באפריל.", [],
        {}, dict(trip_update_bari), {"dates", "travelers", "accessibility", "baggage", "lodging"},
    )
check("turn 0 (Bari): current_question correctly advances straight to "
      "accessibility once dates+travelers are already resolved",
      (result_bari.get("trip_update") or {}).get("guided", {}).get("current_question") == "accessibility")
check("turn 0 (Bari) FIX: dynamic_hint is NOT None even though nothing was "
      "left to redirect to - it asks accessibility instead of silently "
      "giving Tinkerbell no steering at all",
      bool(result_bari.get("dynamic_hint")))
check("turn 0 (Bari) FIX: the hint is specifically the accessibility yes/no "
      "ask, not some generic leftover",
      "התאמות נגישות" in str(result_bari.get("dynamic_hint") or ""))

# =====================================================================
# 2. Direct unit coverage of _guided_incomplete_fields.
# =====================================================================
_state_missing_acc = {
    "requested_services": ["flights"],
    "guided": {"answered": ["dates", "travelers", "baggage"]},
    "flight": {"baggage": ["checked_bag"]},
    "dates": {"departure": "2027-04-10", "return": "2027-04-15"},
    "travelers": {"adults": 2},
}
check("_guided_incomplete_fields: accessibility is reported open when "
      "everything else is already answered",
      chat._guided_incomplete_fields(_state_missing_acc) == ["accessibility"])

_state_all_done = dict(_state_missing_acc)
_state_all_done["guided"] = {"answered": ["dates", "travelers", "baggage", "accessibility"]}
_state_all_done["accessibility"] = {"needed": False}
check("_guided_incomplete_fields: empty once accessibility is also answered",
      chat._guided_incomplete_fields(_state_all_done) == [])

check("_guided_incomplete_fields: known-with-confidence alone (without "
      "guided.answered catching up) also counts as resolved - the same "
      "staleness tolerance the dispatcher's own top-of-function loop "
      "already trusts, never bookkeeping alone",
      chat._guided_incomplete_fields({
          "requested_services": ["flights"], "guided": {"answered": []},
          "accessibility": {"needed": False},
      }) == [])

# Berlin regression (qa_stage3_run3_guided_loop_guard.py): lodging's own
# sub-fields (lodging_type etc.) are deliberately left OUT of guided.
# answered even though lodging reads "complete" - _guided_incomplete_
# fields must never resurrect that loop by treating them as still open.
# Scoped to accessibility only (the one field with no domain-level
# completion signal of its own) - never the full guided_order.
check("_guided_incomplete_fields: never resurrects the Berlin loop - "
      "lodging's own stale sub-field bookkeeping is out of scope entirely, "
      "only accessibility (domain-independent) is ever checked",
      chat._guided_incomplete_fields({
          "requested_services": ["flights", "lodging"],
          "session_status": {"flights": "complete", "lodging": "complete", "car": "declined", "trip_planning": "complete"},
          "guided": {"current_question": "lodging_type", "attempts": 10, "answered": ["dates", "travelers", "baggage", "accessibility"]},
          "lodging": {"details": {"locations": "מיטה, ברלין"}},
          "accessibility": {"needed": False},
      }) == [])

# =====================================================================
# 3. Direct unit coverage of _advance_sessions's widened ready_for_summary.
# =====================================================================
_statuses_all_decided = {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "declined"}
_adv_missing_acc = chat._advance_sessions({
    "session_status": dict(_statuses_all_decided),
    "requested_services": ["flights"],
    "guided": {"answered": ["dates", "travelers", "baggage"]},
    "flight": {"baggage": ["checked_bag"]},
    "dates": {"departure": "2027-04-10", "return": "2027-04-15"},
    "travelers": {"adults": 2},
})
check("_advance_sessions FIX: ready_for_summary stays False while every "
      "domain is complete/declined but accessibility was never asked - "
      "the one real approval moment must not fire yet",
      _adv_missing_acc.get("ready_for_summary") is False)

_adv_acc_done = chat._advance_sessions({
    "session_status": dict(_statuses_all_decided),
    "requested_services": ["flights"],
    "guided": {"answered": ["dates", "travelers", "baggage", "accessibility"]},
    "flight": {"baggage": ["checked_bag"]},
    "dates": {"departure": "2027-04-10", "return": "2027-04-15"},
    "travelers": {"adults": 2},
    "accessibility": {"needed": False},
})
check("_advance_sessions: ready_for_summary correctly becomes True once "
      "accessibility is also genuinely resolved",
      _adv_acc_done.get("ready_for_summary") is True)

# =====================================================================
# 4. HTTP round-trip, turn 0: dates+travelers both stated in the very
#    first message - the live Bari/Valencia shape. _guided_ask_hint must
#    reach trip_update, never get silently popped.
# =====================================================================
def _fake_turn0(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {
                "destination": {"places": ["בארי"], "mode": "specific", "status": "known"},
                "dates": {"departure": "2027-04-10", "return": "2027-04-15"},
                "travelers": {"adults": 2},
            },
            "restart_request": False, "restart_evidence": None,
            "dates_evidence": "ה-10 עד ה-15 באפריל", "destination_evidence": "בארי", "trip_type_evidence": None,
            "link_request": False, "link_request_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "classifier":
        return "false"
    if source == "tinkerbell_reply":
        return "קלטתי, בארי בין ה-10 ל-15 באפריל, שני מבוגרים. מה התקציב לאדם לטיסה?"
    return "{}"


member_turn0 = _make_member("qa-run11-bari-turn0@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_turn0):
    state_turn0 = {
        "destination": {"places": [], "mode": None, "status": "unknown"},
        "active_session": None, "requested_services": [],
        "session_status": {"flights": "pending", "lodging": "pending", "car": "pending", "trip_planning": "pending"},
    }
    r_turn0 = _post("טסים לבארי שניים, ה-10 עד ה-15 באפריל.", [], state_turn0, member_turn0)
tu_turn0 = r_turn0.get("trip_update") or {}
check("HTTP turn 0 (Bari): dates+travelers both landed this same turn",
      bool((tu_turn0.get("dates") or {}).get("departure")) and (tu_turn0.get("travelers") or {}).get("adults") == 2)
check("HTTP turn 0 (Bari) FIX: _guided_ask_hint reaches trip_update instead "
      "of being popped - accessibility is actually asked about",
      "התאמות נגישות" in str(tu_turn0.get("_guided_ask_hint") or ""))
check("HTTP turn 0 (Bari): current_question is accessibility",
      (tu_turn0.get("guided") or {}).get("current_question") == "accessibility")

# =====================================================================
# 5. HTTP round-trip, case A's later-turns shape: every domain already
#    complete/declined, accessibility still genuinely open, and
#    Tinkerbell's own reply stubbornly tries to send the final מאשרת
#    summary anyway (exactly the live symptom - the hint existed and she
#    overrode it regardless). The reserved מאשר phrase must never reach
#    the customer while accessibility is still unresolved, and
#    final_summary_shown must never be set.
# =====================================================================
def _fake_stubborn_summary(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
            "link_request": False, "link_request_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "classifier":
        return "false"
    if source == "tinkerbell_reply":
        return "מצוין, פרטי הטיסה לבארי סגורים! אם כל הפרטים נכונים, כתבי מאשרת."
    return "{}"


member_a5 = _make_member("qa-run11-bari-turn5@example.com")
_real_session_gaps = chat._session_gaps
with patch.object(chat, "_post_claude", side_effect=_fake_stubborn_summary), \
     patch.object(chat, "_session_gaps", side_effect=lambda state, session: [] if session == "flights" else _real_session_gaps(state, session)):
    state_a5 = {
        "destination": {"places": ["בארי"], "mode": "specific", "status": "known"},
        "active_session": None,
        "requested_services": ["flights"],
        "session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
        "dates": {"departure": "2027-04-10", "return": "2027-04-15"},
        "travelers": {"adults": 2},
        "flight": {"baggage": ["checked_bag"]},
        "trip_type": "leisure",
        "departure_airport": "TLV",
        "budget_per_person": 500,
        "guided": {"current_question": None, "answered": ["dates", "travelers", "baggage"], "mixed_baggage_pending": False},
        "next_session": None,
    }
    r_a5 = _post("תודה, מצוין", [{"role": "assistant", "content": "קלטתי."}], state_a5, member_a5)
tu_a5 = r_a5.get("trip_update") or {}
reply_a5 = str(r_a5.get("reply") or "")
check("HTTP turns 5-10 (case A) FIX: the dispatcher's own early-exit gate "
      "stays open (widened by _guided_incomplete_fields) - accessibility "
      "becomes current_question even though every domain already reads "
      "complete/declined",
      (tu_a5.get("guided") or {}).get("current_question") == "accessibility")
check("HTTP turns 5-10 (case A) FIX: ready_for_summary never goes True "
      "while accessibility is still genuinely unresolved",
      tu_a5.get("ready_for_summary") is False)
check("HTTP turns 5-10 (case A) FIX: the reserved מאשר/מאשרת phrase never "
      "reaches the customer - intercepted/overridden even though "
      "Tinkerbell's own mocked reply stubbornly tried to send it",
      "מאשר" not in reply_a5)
check("HTTP turns 5-10 (case A) FIX: final_summary_shown is never set once "
      "the premature reply was overridden",
      not tu_a5.get("final_summary_shown"))

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE email LIKE 'qa-run11-%@example.com'")
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL RUN-11 ACCESSIBILITY-HINT-GATE TESTS PASSED")
