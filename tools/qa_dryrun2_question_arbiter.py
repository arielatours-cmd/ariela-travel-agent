"""QA for the single-question arbiter (business owner approved direction,
22.10.2026, after dry-run 2's findings 2-4, qa/reports/2026-10-22-
dryrun2.md). See _turn_question_arbiter's own docstring for the full
history. This file covers:

- Direct priority-ordering unit tests (clarify > shift/mixed-baggage >
  guided > repeat/resume), including Shlomo's explicit addition: guided's
  own hint, when it's actually the mixed-baggage payment-time yes/no
  (guided.mixed_baggage_pending), is a direct-continuation question, not
  the standing background one.
- The run-10/#140 dangling-fragment class of bug: once only the winner is
  injected, a losing hint's own text (e.g. the accessibility disclaimer)
  never appears in the prompt at all when something else wins - nothing
  left to compose, then abandon, mid-sentence.
- The new _force_guided_field_retry helper, reused by the closing_claim
  "deceptive success" safety net (dry-run 2, case E): a false "מעבירה
  אותך..." claim with every DOMAIN already complete/declined but
  accessibility still genuinely open (outside any single domain) used to
  sail straight through, since closing_claim's own pending_domain check
  only ever looked at the four domains - the premature-מאשרת safety net
  only catches the literal מאשר/מאשרת wording, which this phrasing never
  used either.

Run: python3 tools/qa_dryrun2_question_arbiter.py
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
            ("QA dryrun2 arbiter", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
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
# 1. Direct priority-ordering unit tests.
# =====================================================================
check("priority 1: _gap_clarify_question wins over everything else",
      chat._turn_question_arbiter({
          "_gap_clarify_question": "משהו לא ברור",
          "_shift_candidate_hint": "שאלת הזזה",
          "_guided_ask_hint": "שאלת guided",
      })[1] == "gap_clarify")

check("priority 2: _shift_candidate_hint wins over the standing guided question",
      chat._turn_question_arbiter({
          "_shift_candidate_hint": "שאלת הזזה",
          "_guided_ask_hint": "שאלת guided רגילה",
          "guided": {"mixed_baggage_pending": False},
      }) == ("שאלת הזזה", "shift_candidate"))

check("priority 2 (Shlomo's explicit addition): guided's own hint, when "
      "mixed_baggage_pending is set, is labeled as the direct-continuation "
      "tier, not the plain standing question",
      chat._turn_question_arbiter({
          "_guided_ask_hint": "הסבר על תשלום בזמן ההזמנה + שאלת כן/לא",
          "guided": {"mixed_baggage_pending": True},
      }) == ("הסבר על תשלום בזמן ההזמנה + שאלת כן/לא", "guided_mixed_baggage"))

check("priority 3: the plain standing guided question wins when nothing "
      "higher-priority is live",
      chat._turn_question_arbiter({
          "_guided_ask_hint": "שאלת נגישות",
          "guided": {"mixed_baggage_pending": False},
      }) == ("שאלת נגישות", "guided"))

check("priority 4: _gap_repeat_rephrase_hint wins only when nothing above it is live",
      chat._turn_question_arbiter({"_gap_repeat_rephrase_hint": "ניסוח מחדש"}) == ("ניסוח מחדש", "gap_repeat_rephrase"))
check("priority 4: _resume_choice_hint wins only when nothing above it is live",
      chat._turn_question_arbiter({"_resume_choice_hint": "להמשיך או חדש"}) == ("להמשיך או חדש", "resume_choice"))
check("nothing live: returns (None, None)", chat._turn_question_arbiter({}) == (None, None))
check("a losing hint's own state is never read/mutated by the arbiter - "
      "pure selection, no side effects possible by construction (same "
      "dict in, same dict out)",
      (lambda s: (chat._turn_question_arbiter(s), s))({"_guided_ask_hint": "x", "_shift_candidate_hint": "y"})[1]
      == {"_guided_ask_hint": "x", "_shift_candidate_hint": "y"})

# =====================================================================
# 2. End-to-end: only the winner's text ever reaches Tinkerbell's prompt -
# a losing one-shot question hint's own wording (e.g. the accessibility
# disclaimer) is never concatenated into system_dynamic at all, removing
# the run-10/#140 dangling-fragment competition by construction.
# =====================================================================
_captured_prompts = {}


def _capture_tinkerbell_prompt(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "tinkerbell_reply":
        _captured_prompts["system_dynamic"] = system_dynamic
        return "בסדר, אז בוא נזיז את התאריכים יום אחד."
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_capture_tinkerbell_prompt):
    chat._call_tinkerbell(
        "fakekey", "fake-model", [], "אפשר להזיז יום אחד?",
        state={
            "_shift_candidate_hint": "שאלת הזזה חיה",
            "_guided_ask_hint": "הפרט הבא לברר: האם מישהו מהנוסעים צריך התאמות נגישות",
            "guided": {"mixed_baggage_pending": False},
            "session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
        },
    )
_prompt_text = _captured_prompts.get("system_dynamic") or ""
check("end-to-end: the winning hint's text (shift) reaches the prompt",
      "שאלת הזזה חיה" in _prompt_text)
check("end-to-end: exactly ONE question gets the 'this is the only thing "
      "to ask this turn' priority framing - never two competing 'ask "
      "about X' instructions in the same prompt (the mechanism that fixes "
      "the run-10/#140 dangling-fragment class of leak; the raw state "
      "JSON dump further down may still mention the losing hint's stored "
      "value as inert context - that's unrelated and expected)",
      _prompt_text.count("השאלה/הנחיה הבאה היא הדבר היחיד") == 1)

# =====================================================================
# 3. closing_claim + _force_guided_field_retry: dry-run 2 case E - every
# domain complete/declined, accessibility still genuinely open, and
# Tinkerbell's reply falsely claims an action ("מעבירה אותך לתוצאות
# הטיסה") that never happened. The premature-מאשרת gate doesn't catch
# this phrasing (no literal מאשר/מאשרת) - closing_claim must.
# =====================================================================
def _fake_closing_claim_turn(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
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
        if "התאמות נגישות" in str(system_dynamic or ""):
            return "לפני שנסגור הכל - יש למישהו מכן צורך בהתאמת נגישות לאורך הטיול?"
        return "בסדר גמור. מעבירה אותך לתוצאות הטיסה - ותמיד אפשר לחזור לכאן."
    return "{}"


member_e = _make_member("qa-dryrun2-closing-claim@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_closing_claim_turn):
    state_e = {
        "destination": {"places": ["רוביני"], "mode": "specific", "status": "known"},
        "active_session": None,
        "requested_services": ["flights"],
        "session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
        "dates": {"departure": "2027-07-02", "return": "2027-07-06"},
        "travelers": {"adults": 3},
        "flight": {"baggage": ["carry_on_only"]},
        "trip_type": "leisure",
        "departure_airport": "TLV",
        "destination_airports": ["PUY"],
        "budget_per_person": 1100,
        "guided": {"current_question": None, "answered": ["dates", "travelers", "baggage"], "mixed_baggage_pending": False},
        "next_session": None,
    }
    r_e = _post("לא", [{"role": "assistant", "content": "רוצים גם רכב?"}], state_e, member_e)
tu_e = r_e.get("trip_update") or {}
reply_e = str(r_e.get("reply") or "")
check("dry-run 2 case E FIX: the false 'מעבירה אותך' closing claim never "
      "reaches the customer while accessibility is still genuinely open - "
      "closing_claim's own forced retry catches what the premature-מאשרת "
      "gate's literal-phrase check could not",
      "מעבירה אותך" not in reply_e)
check("dry-run 2 case E FIX: the forced retry actually asked accessibility, "
      "not just a generic fallback",
      "נגישות" in reply_e)
check("current_question correctly became accessibility via the forced retry",
      (tu_e.get("guided") or {}).get("current_question") == "accessibility")

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE email LIKE 'qa-dryrun2-%@example.com'")
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DRY-RUN-2 QUESTION-ARBITER TESTS PASSED")
