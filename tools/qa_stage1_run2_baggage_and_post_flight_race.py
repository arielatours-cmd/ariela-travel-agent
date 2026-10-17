"""QA for Shaked's stage-1, run-2 live findings (16.10.2026, qa/reports/
2026-10-16-stage1-run2.md on the shaked branch, commit 3feca37): 0/5
scenarios passed on main 43a59a8 (#54+#55).

Bug 1 (all 5 scenarios): the baggage question was consistently asked as
"X, Y, or Z?" ("איזו כבודה תרצו לקחת - טרולי, מזוודה בבטן המטוס, או רק
תיק קטן?"), violating the one-question-per-message iron rule, even though
TINKERBELL_SYSTEM already told Tinkerbell not to phrase it that way.
Root cause traced (not a code bug - a prompt-adjacency problem): the one
field-specific baggage instruction listed the three canonical storage
values ("טרולי בלבד", "מזוודה בבטן המטוס", "תיק קטן") in the SAME
sentence as the "ask it as an open question" instruction - handing the
model an enumerable list right next to the "don't enumerate" rule, every
single time. budget_per_person and connection_preference never have this
problem because their own guidance never names discrete category values
at all. Fixed by moving the phrasing instruction into the prompt's very
first paragraph (the main one-question-per-message rule, which Tinkerbell
reads before any field-specific mention), as a strong, named negative
example quoting the exact failing phrasing live tests kept producing -
and leaving the value-recording instruction on its own, with no
adjacent list to echo into the question. This is a prompt-only fix with
no deterministic enforcement; this QA checks the prompt text itself, not
live model output (an LLM's phrasing can't be asserted on deterministically).

Bug 2 (U1, U2, U4, U5): post_flight_offer is set purely from state shape
(next_session set, active_session empty) the moment flights' missing_
required empties out - with NO check on what Tinkerbell's reply that turn
actually asked. The SAME turn, Tinkerbell asked the separate, optional
"is a direct flight important to you?" question instead of the real
continuation offer. The customer's answer to THAT question then got
misread as answering the stale post_flight_offer flag still sitting in
state: "בטח" wrongly activated trip_planning and immediately asked "tell
me what you like to do on vacation" (never asked if a route was wanted
at all); "לא משנה לנו"/"לא צריך" wrongly declined trip_planning the same
way. The real continuation offer only ever arrived later, after lodging
and car, since trip_planning was now marked decided.

Fixed: before trusting a stored post_flight_offer as "this reply answers
it", check the actual last assistant message's last question clause
(_last_question_clause - the same mechanism _deterministic_connection_
preference_facts and siblings already use for this exact bug class). If
it plainly asks one of flights' own remaining optional questions (direct/
baggage/budget - never genuine post-flight-offer topics), this message
answers THAT question, not the stale offer - post_flight_offer stays
pending for a turn where Tinkerbell actually asks it.

Run: python3 tools/qa_stage1_run2_baggage_and_post_flight_race.py
"""
import os
import sys
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
            ("QA Stage1 Run2", email, generate_password_hash("Test1234!"),
             datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


# === Bug 1: TINKERBELL_SYSTEM prompt text ===

check("the baggage canonical-values line no longer carries the 'X, Y, or Z' "
      "question-phrasing example right next to the enumerable value list",
      '"X, Y, או Z?"' not in chat.TINKERBELL_SYSTEM)
check("the main one-question-per-message rule now names the live failing "
      "baggage phrasing as an explicit, forbidden example",
      "טרולי, מזוודה בבטן המטוס, או רק תיק קטן" in chat.TINKERBELL_SYSTEM)
check("the baggage canonical storage values are still fully specified "
      "(needed for correct state extraction) - fix didn't drop them",
      all(v in chat.TINKERBELL_SYSTEM for v in ('"טרולי בלבד"', '"מזוודה בבטן המטוס"', '"תיק קטן"')))
check("the forbidden-example baggage phrasing appears textually close to "
      "the existing 'X או Y' iron rule, not next to the value-recording line",
      chat.TINKERBELL_SYSTEM.index("טרולי, מזוודה בבטן המטוס, או רק תיק קטן")
      < chat.TINKERBELL_SYSTEM.index('תעדי אך ורק באחד מהערכים האלה'))

# === Bug 2: post_flight_offer race with flights' own optional questions ===

member_id = _make_member("qa-stage1-run2@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id


def _fake_post_claude(key, model, system_static, system_dynamic, history, message,
                       max_tokens, include_history=True, source="other"):
    if source in ("state_extractor", "classifier"):
        return "{}"
    return "תשובה לדוגמה מאריאלה."


# --- 1. Exact live repro (U1, Rome/כל יעד): flights just completed,
#        post_flight_offer was stamped to trip_planning on THIS same turn
#        (by the generic next_session/active_session rule), but the actual
#        question Tinkerbell asked this turn is the optional direct-flight
#        one. "בטח" must NOT silently activate trip_planning. ---
HISTORY_DIRECT_QUESTION = [
    {"role": "user", "content": "התקציב שלנו עד 3000 לאדם"},
    {"role": "assistant", "content": "מעולה, נרשם. חשוב לכם שהטיסה תהיה ישירה?"},
]
STATE_U1 = {
    "destination": {"places": ["רומא"], "mode": "specific", "status": "known"},
    "active_session": None,
    "next_session": "trip_planning",
    "post_flight_offer": ["trip_planning"],
    "requested_services": ["flights", "trip_planning"],
    "session_status": {"flights": "complete", "trip_planning": "pending"},
}
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r1 = client.post("/api/ariella/chat-clean", json={
        "message": "בטח", "history": HISTORY_DIRECT_QUESTION, "trip_state": dict(STATE_U1),
    })
tu1 = (r1.get_json() or {}).get("trip_update") or {}
check("U1 repro: 'בטח' answering the direct-flight question does NOT "
      "activate trip_planning (the stale post_flight_offer is not consumed)",
      (tu1.get("session_status") or {}).get("trip_planning") != "active")
check("U1 repro: trip_planning is not silently added to requested_services either",
      not ((tu1.get("session_status") or {}).get("trip_planning") == "active"
           and "trip_planning" in (tu1.get("requested_services") or [])))

# --- 2. Exact live repro (U2/U4/U5): same shape, but the customer DECLINES
#        the direct-flight question ("לא צריך") - must NOT be read as
#        declining trip_planning either. ---
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r2 = client.post("/api/ariella/chat-clean", json={
        "message": "לא צריך", "history": HISTORY_DIRECT_QUESTION, "trip_state": dict(STATE_U1),
    })
tu2 = (r2.get_json() or {}).get("trip_update") or {}
check("U2/U4/U5 repro: 'לא צריך' answering the direct-flight question does "
      "NOT decline trip_planning",
      (tu2.get("session_status") or {}).get("trip_planning") != "declined")

# --- 3. Same shape, baggage question instead of direct - same bug class ---
HISTORY_BAGGAGE_QUESTION = [
    {"role": "assistant", "content": "מעולה, נרשם. איזו כבודה תרצו לקחת?"},
]
STATE_BAGGAGE = dict(STATE_U1)
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r3 = client.post("/api/ariella/chat-clean", json={
        "message": "סבבה", "history": HISTORY_BAGGAGE_QUESTION, "trip_state": dict(STATE_BAGGAGE),
    })
tu3 = (r3.get_json() or {}).get("trip_update") or {}
check("baggage-question variant: a bare 'סבבה' does not activate trip_planning either",
      (tu3.get("session_status") or {}).get("trip_planning") != "active")

# --- 4. Regression: a genuine, freely-worded continuation offer (NOT one
#        of flights' own remaining questions) still gets answered normally -
#        the fix must not break the original post_flight_offer_from_next_
#        session mechanism it sits next to. ---
HISTORY_REAL_OFFER = [
    {"role": "assistant", "content": "מצוין, הטיסות סגורות. בואי נדבר רגע על המסלול - מה אתם אוהבים לעשות בחופשה?"},
]
STATE_REAL_OFFER = dict(STATE_U1)
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r4 = client.post("/api/ariella/chat-clean", json={
        "message": "בטח", "history": HISTORY_REAL_OFFER, "trip_state": dict(STATE_REAL_OFFER),
    })
tu4 = (r4.get_json() or {}).get("trip_update") or {}
check("regression: a genuine continuation-offer question still activates "
      "trip_planning normally when 'בטח' answers it",
      (tu4.get("session_status") or {}).get("trip_planning") == "active")

# --- 5. Regression: _last_question_clause itself correctly isolates the
#        direct-flight question even when combined with an unrelated
#        statement in the same message (the class of bug this reuses the
#        existing fix for). ---
combined = "אין כרגע טיסה ישירה זמינה בתאריכים האלה. חשוב לכם שהטיסה תהיה ישירה בכל זאת?"
check("_last_question_clause isolates the real question from a combined statement+question",
      "ישיר" in chat._last_question_clause(combined))

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL STAGE1-RUN2-BAGGAGE-AND-POST-FLIGHT-RACE TESTS PASSED")
