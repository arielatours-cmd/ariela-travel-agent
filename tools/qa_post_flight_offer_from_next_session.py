"""QA for Shaked's live finding (2026-10-16, Athens/Budapest stage-1): a
plain "לא" after a flight (or other domain) session closed was NOT
recognized, when Tinkerbell phrased the continuation offer freely in her
own words.

Root cause: trip_update["post_flight_offer"] was previously only ever set
by specific hard-coded-text branches in chat_clean() (e.g. the generic
"תרצי שאמשיך גם עם X?" branch). Once the business owner's one-option-per-
question principle (2026-10-16) replaced fixed question phrasings with
Ariella phrasing things herself, a freely-worded continuation offer had no
code path setting post_flight_offer at all - so a customer's "לא" to it had
nothing to attach to, and the same offer was asked again next turn instead
of being understood as a decline.

Fix: right after the final _advance_sessions(trip_update) call in
chat_clean(), whenever next_session is set and nothing is active (exactly
the moment a plain yes/no continuation offer is being made, per
_advance_sessions' own contract), trip_update["post_flight_offer"] is set
to [next_session] - regardless of which code path produced the reply text
this turn. This is driven purely by the authoritative structured state, not
by matching any particular phrasing.

Run: python3 tools/qa_post_flight_offer_from_next_session.py
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
            ("QA Post Flight Offer Next Session", email, generate_password_hash("Test1234!"),
             datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


# A deliberately NOVEL continuation-offer phrasing - not the hard-coded
# "תרצי שאמשיך גם עם X?" sentence, and not shaped like
# _infer_post_flight_offer_from_text's own offer-cue patterns either, to
# prove the fix does not depend on recognizing any particular text at all.
FREELY_WORDED_OFFER = "מצוין, הטיסות ללונדון סגורות מצדי. בואי נדבר רגע על איפה תרצו לישון שם?"


def _fake_post_claude_freeform_offer(key, model, system_static, system_dynamic, history, message,
                                      max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return "{}"
    if source == "classifier":
        return "{}"
    return FREELY_WORDED_OFFER


HISTORY_1 = [
    {"role": "user", "content": "אני רוצה לטוס ללונדון, טיסות, לינה ורכב"},
]
STATE_BEFORE_TURN1 = {
    "destination": {"places": ["לונדון"], "mode": "specific", "status": "known"},
    "active_session": None,
    "requested_services": ["flights", "lodging", "car"],
    "session_status": {"flights": "complete", "trip_planning": "declined", "lodging": "pending", "car": "pending"},
}

member_id = _make_member("qa-post-flight-next-session@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id

print("=== TURN 1: nothing active, lodging is next_pending; Tinkerbell phrases the offer freely ===")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_freeform_offer):
    r1 = client.post("/api/ariella/chat-clean", json={
        "message": "תודה", "history": HISTORY_1, "trip_state": dict(STATE_BEFORE_TURN1),
    })
data1 = r1.get_json()
tu1 = data1.get("trip_update") or {}
print("reply:", data1.get("reply"))
print("post_flight_offer:", tu1.get("post_flight_offer"))
check("the freely-worded offer is returned to the client untouched",
      data1.get("reply") == FREELY_WORDED_OFFER)
check("post_flight_offer is set to ['lodging'] purely from next_session, "
      "with no dependency on the reply's own wording",
      tu1.get("post_flight_offer") == ["lodging"])
check("active_session stays None (an offer, not an activation)",
      tu1.get("active_session") is None)

HISTORY_2 = HISTORY_1 + [
    {"role": "user", "content": "תודה"},
    {"role": "assistant", "content": FREELY_WORDED_OFFER},
]

print("\n=== TURN 2: a plain 'לא' answers the freely-worded offer ===")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_freeform_offer):
    r2 = client.post("/api/ariella/chat-clean", json={
        "message": "לא", "history": HISTORY_2, "trip_state": dict(tu1),
    })
data2 = r2.get_json()
tu2 = data2.get("trip_update") or {}
print("reply:", data2.get("reply"))
print("session_status:", tu2.get("session_status"))
print("post_flight_offer:", tu2.get("post_flight_offer"))
check("'לא' declines lodging instead of being misunderstood",
      (tu2.get("session_status") or {}).get("lodging") == "declined")
check("lodging is removed from requested_services",
      "lodging" not in (tu2.get("requested_services") or []))
check("the chain continues: post_flight_offer now offers the NEXT pending domain (car)",
      tu2.get("post_flight_offer") == ["car"])

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL POST-FLIGHT-OFFER-FROM-NEXT-SESSION TESTS PASSED")
