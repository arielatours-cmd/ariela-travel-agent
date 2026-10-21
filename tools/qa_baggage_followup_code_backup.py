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

Reworked per Shaked's rejection of the first version: the original two
signals (a hint-marker set by _baggage_followup_hint, and a guided-
dispatcher current_question transition) both keyed off the guided
dispatcher's own bookkeeping - on her live repro (s1z1 Budapest, s1z3
Rome) current_question was already None and _baggage_followup_hint was
never even built that turn, so NEITHER signal ever fired, and the code
backup never ran. The trigger is now a pure STATE DIFF instead: this
turn's flight.baggage went from empty/unset (trip_state, before) to a
real value (trip_update, now) - independent of which code path produced
that change. The duplicate-content check was also broadened from two
exact fixed phrases (fragile) to a general "mentions adding a trolley/
suitcase" check.

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


_PRIOR_NO_BAGGAGE = {"flight": {}}
_PRIOR_BAGGAGE_ALREADY_KNOWN = {"flight": {"baggage": ["personal_item"]}}

# =====================================================================
# Direct unit tests of _ensure_baggage_followup_note_present.
# =====================================================================
check("baggage was already known BEFORE this turn (no state change) -> "
      "reply left completely untouched, even with a fresh baggage value "
      "still present now",
      chat._ensure_baggage_followup_note_present(
          "מה התקציב שלכם?",
          dict(flight={"baggage": ["personal_item"]}),
          _PRIOR_BAGGAGE_ALREADY_KNOWN,
      ) == "מה התקציב שלכם?")

check("baggage just became known this turn (personal_item), and the "
      "reply already mentions adding a suitcase -> left untouched "
      "(already compliant)",
      chat._ensure_baggage_followup_note_present(
          "אפשר תמיד להוסיף מזוודה בהזמנה. מה התקציב שלכם?",
          dict(flight={"baggage": ["personal_item"]}),
          _PRIOR_NO_BAGGAGE,
      ) == "אפשר תמיד להוסיף מזוודה בהזמנה. מה התקציב שלכם?")

check("baggage just became known (personal_item - hand bag only) but "
      "the model's reply DROPPED the note entirely -> code inserts the "
      "trolley-OR-suitcase sentence before the rest",
      "להוסיף טרולי" in chat._ensure_baggage_followup_note_present(
          "מה התקציב שלכם לאדם לטיסה?",
          dict(flight={"baggage": ["personal_item"]}),
          _PRIOR_NO_BAGGAGE,
      ))

check("same drop, but carry_on_only (a trolley just chosen) -> code "
      "inserts the suitcase-only sentence, not the trolley-or-suitcase one",
      "להוסיף מזוודה" in chat._ensure_baggage_followup_note_present(
          "מה התקציב שלכם לאדם לטיסה?",
          dict(flight={"baggage": ["carry_on_only"]}),
          _PRIOR_NO_BAGGAGE,
      ) and "להוסיף טרולי" not in chat._ensure_baggage_followup_note_present(
          "מה התקציב שלכם לאדם לטיסה?",
          dict(flight={"baggage": ["carry_on_only"]}),
          _PRIOR_NO_BAGGAGE,
      ))

check("checked_bag (the top tier) never gets a note inserted even when "
      "it just became known this turn",
      chat._ensure_baggage_followup_note_present(
          "מה התקציב שלכם לאדם לטיסה?",
          dict(flight={"baggage": ["checked_bag"]}),
          _PRIOR_NO_BAGGAGE,
      ) == "מה התקציב שלכם לאדם לטיסה?")

check("the inserted sentence comes BEFORE the rest of the reply, as one "
      "combined message",
      chat._ensure_baggage_followup_note_present(
          "מה התקציב שלכם לאדם לטיסה?",
          dict(flight={"baggage": ["personal_item"]}),
          _PRIOR_NO_BAGGAGE,
      ).endswith("מה התקציב שלכם לאדם לטיסה?"))

check("never raises on a None/empty reply, still inserts the note alone",
      bool(chat._ensure_baggage_followup_note_present(
          None, dict(flight={"baggage": ["personal_item"]}), _PRIOR_NO_BAGGAGE
      )))

check("no trip_state passed at all (defaults to {}) is treated the same "
      "as 'no prior baggage' - still fires",
      "להוסיף" in chat._ensure_baggage_followup_note_present(
          "מה התקציב שלכם?", dict(flight={"baggage": ["personal_item"]})
      ))

# =====================================================================
# Broadened duplicate-content detection: not just the two original exact
# phrases, but any "להוסיף" + טרולי/מזוודה co-occurrence, in whatever
# surrounding wording.
# =====================================================================
check("a differently-worded but equivalent note ('ניתן גם להוסיף טרולי "
      "בהמשך') is recognized as already present - no double note",
      chat._ensure_baggage_followup_note_present(
          "ניתן גם להוסיף טרולי בהמשך. מה התקציב?",
          dict(flight={"baggage": ["personal_item"]}),
          _PRIOR_NO_BAGGAGE,
      ) == "ניתן גם להוסיף טרולי בהמשך. מה התקציב?")

check("a reply that mentions טרולי/מזוודה WITHOUT 'להוסיף' at all (e.g. "
      "just naming the chosen tier) is NOT treated as already compliant - "
      "the note is still inserted",
      "אפשר תמיד להוסיף" in chat._ensure_baggage_followup_note_present(
          "קלטתי, טרולי. מה התקציב?",
          dict(flight={"baggage": ["carry_on_only"]}),
          _PRIOR_NO_BAGGAGE,
      ))

# =====================================================================
# Regression: baggage was the active guided question and still is (not
# yet answered this turn) - no state change happened, so no note.
# =====================================================================
check("baggage still pending (no value yet) -> never fires",
      chat._ensure_baggage_followup_note_present(
          "מה סוג הכבודה?", dict(flight={}), _PRIOR_NO_BAGGAGE,
      ) == "מה סוג הכבודה?")

# =====================================================================
# End-to-end: a mocked Tinkerbell reply that drops the note entirely
# still reaches the customer WITH the note, inserted by the code backup -
# reproducing Shaked's exact live shape where the guided dispatcher's own
# current_question was already None this turn (baggage answered via the
# general extractor, not the guided dispatcher's own baggage question).
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
    "flight": {},
    # Shaked's exact live repro: the guided dispatcher's own bookkeeping
    # is already past baggage (current_question is None/something else)
    # by the time baggage actually gets answered via the general
    # extractor - the old hint/current_question signals both miss this.
    "guided": {"current_question": None, "attempts": 0, "answered": ["dates", "travelers", "baggage"]},
}


def _post_claude_baggage_answer(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {"flight": {"baggage": ["personal_item"]}},
            "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
            "relative_date_hint": None, "relative_date_hint_evidence": None,
            "link_request": False, "link_request_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
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
check("end-to-end (Shaked's exact repro shape - guided.current_question "
      "already None, baggage answered via the general extractor): a "
      "dropped baggage follow-up note is still restored by the code "
      "backup, via the pure flight.baggage state-diff trigger",
      "להוסיף" in reply and "מה התקציב" in reply)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL BAGGAGE-FOLLOWUP-CODE-BACKUP TESTS PASSED")
