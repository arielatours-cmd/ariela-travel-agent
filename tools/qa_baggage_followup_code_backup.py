"""QA for Shlomo's relay of Shaked's live stage-1 run-2 finding: the
"can always add a trolley/suitcase later" baggage follow-up note still
didn't reliably reach the customer, even after its own prompt instruction
was hardened twice already (PR #104). Per the business owner's explicit
direction: this is now ALSO a deterministic code backup, not just a
prompt hint - if the model's own reply doesn't include the note's
content, the code inserts one short sentence itself, before the rest of
the reply. The sentence depends on the current choice: personal_item (a
hand bag only) -> can add a trolley OR a suitcase; carry_on_only (a
trolley) -> can add a suitcase. A checked bag (the top tier) never needs
a note.

_ensure_baggage_followup_note_present detects whether a note was
INSTRUCTED this turn via a unique marker substring already present in
_baggage_followup_hint's own text, carried in
trip_update["_guided_ask_hint"] - no new state field needed - and then
checks the ACTUAL reply for either variant's content before deciding to
insert anything.

Run: python3 tools/qa_baggage_followup_code_backup.py
"""
import os
import sys
import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

import ariella_chat_clean as chat
import app as app_module
from werkzeug.security import generate_password_hash

DB = database.DB_PATH
client = app_module.app.test_client()

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


_HINT_PRESENT = {"_guided_ask_hint": "...טרולי או מזוודה... " + chat._BAGGAGE_FOLLOWUP_HINT_MARKER + " ...מה התקציב..."}
_HINT_ABSENT = {"_guided_ask_hint": "מה התקציב שלכם לאדם לטיסה?"}

# =====================================================================
# Direct unit tests of _ensure_baggage_followup_note_present.
# =====================================================================
check("no note was instructed this turn (hint has no marker) -> reply "
      "left completely untouched",
      chat._ensure_baggage_followup_note_present("מה התקציב שלכם?", _HINT_ABSENT)
      == "מה התקציב שלכם?")

check("a note WAS instructed, and the reply already mentions adding a "
      "suitcase -> left untouched (already compliant)",
      chat._ensure_baggage_followup_note_present(
          "אפשר תמיד להוסיף מזוודה בהזמנה. מה התקציב שלכם?",
          dict(_HINT_PRESENT, flight={"baggage": ["personal_item"]}),
      ) == "אפשר תמיד להוסיף מזוודה בהזמנה. מה התקציב שלכם?")

check("a note was instructed but the model's reply DROPPED it entirely "
      "(personal_item - hand bag only) -> code inserts the "
      "trolley-OR-suitcase sentence before the rest",
      "להוסיף טרולי" in chat._ensure_baggage_followup_note_present(
          "מה התקציב שלכם לאדם לטיסה?",
          dict(_HINT_PRESENT, flight={"baggage": ["personal_item"]}),
      ))

check("same drop, but carry_on_only (a trolley already chosen) -> code "
      "inserts the suitcase-only sentence, not the trolley-or-suitcase one",
      "להוסיף מזוודה" in chat._ensure_baggage_followup_note_present(
          "מה התקציב שלכם לאדם לטיסה?",
          dict(_HINT_PRESENT, flight={"baggage": ["carry_on_only"]}),
      ) and "להוסיף טרולי" not in chat._ensure_baggage_followup_note_present(
          "מה התקציב שלכם לאדם לטיסה?",
          dict(_HINT_PRESENT, flight={"baggage": ["carry_on_only"]}),
      ))

check("checked_bag (the top tier) never gets a note inserted, even if "
      "the hint marker is somehow present",
      chat._ensure_baggage_followup_note_present(
          "מה התקציב שלכם לאדם לטיסה?",
          dict(_HINT_PRESENT, flight={"baggage": ["checked_bag"]}),
      ) == "מה התקציב שלכם לאדם לטיסה?")

check("the inserted sentence comes BEFORE the rest of the reply, as one "
      "combined message",
      chat._ensure_baggage_followup_note_present(
          "מה התקציב שלכם לאדם לטיסה?",
          dict(_HINT_PRESENT, flight={"baggage": ["personal_item"]}),
      ).endswith("מה התקציב שלכם לאדם לטיסה?"))

check("never raises on a None/empty reply, still inserts the note alone",
      bool(chat._ensure_baggage_followup_note_present(
          None, dict(_HINT_PRESENT, flight={"baggage": ["personal_item"]})
      )))

# =====================================================================
# End-to-end: a mocked Tinkerbell reply that drops the note entirely
# still reaches the customer WITH the note, inserted by the code backup.
# =====================================================================
def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports,gender) "
            "VALUES(?,?,?,?,?,?,?,?)",
            ("QA Baggage Followup Backup", email, generate_password_hash("Test1234!"),
             datetime.now(timezone.utc).isoformat(), "active", 0, "[]", "female"),
        )
        return cur.lastrowid


member = _make_member("qa-baggage-followup-backup@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member

base_state = {
    "trip_type": "standard",
    "destination": {"places": ["רומא"], "mode": "specific", "status": "known"},
    "destination_airports": ["FCO"],
    "departure_airport": "TLV",
    "travelers": {"adults": 2, "children": 0},
    "dates": {"departure": "2026-11-10", "return": "2026-11-17", "needs_confirmation": False},
    "requested_services": ["flights"],
    "service_decisions": {"flights": {"wanted": True}},
    "session_status": {"flights": "active", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
    "active_session": "flights",
    "guided": {"current_question": "baggage", "attempts": 0, "answered": ["dates", "travelers"]},
}


def _post_claude_baggage_answer(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "guided_extract":
        return json.dumps({
            "status": "answered", "no_baggage": False, "mixed_per_passenger": False,
            "items": [{"type": "personal_item", "count": None, "size": None}],
            "confidence": "high", "also_mentioned": None, "correction": None,
        })
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
            "relative_date_hint": None, "relative_date_hint_evidence": None,
            "link_request": False, "link_request_evidence": None,
        })
    if source == "tinkerbell_reply":
        # The model drops the follow-up note entirely and only asks the
        # next question - exactly the live finding this QA covers.
        return "מה התקציב שלכם לאדם לטיסה?"
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_post_claude_baggage_answer):
    r = client.post("/api/ariella/chat-clean", json={
        "message": "רק תיק יד",
        "history": [{"role": "assistant", "content": "איזו כבודה תרצו לקחת?"}],
        "trip_state": base_state,
    })
data = r.get_json() or {}
reply = str(data.get("reply") or "")
check("end-to-end: a dropped baggage follow-up note is restored by the "
      "code backup when the model's reply omits it",
      "להוסיף" in reply and "מה התקציב" in reply)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL BAGGAGE-FOLLOWUP-CODE-BACKUP TESTS PASSED")
