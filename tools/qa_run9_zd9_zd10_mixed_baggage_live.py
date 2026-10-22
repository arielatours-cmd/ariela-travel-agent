"""QA for Shaked's live run-9 findings on PR #128 AFTER it merged to main
(90d98d2) - relayed by Shlomo, 22.10.2026:

zd9 (Bilbao): after the mixed-baggage payment-time question, the customer
replied "נלך על מזוודה לכולם" ("let's go with a suitcase for everyone") -
an affirmative answer to "choose the same baggage for everyone?" that ALSO
states the chosen type in the same breath. The general extractor
(EXTRACTOR_SYSTEM), which runs on every turn regardless of guided
dispatch, read this as a perfectly legitimate single-type baggage
statement by its own instructions and wrote flight.baggage=["checked_bag"]
directly - bypassing the guided dispatch's own "yes" path entirely, which
is supposed to ask the normal baggage question NEXT turn with nothing
saved yet.

Root cause: nothing blocked flight.baggage from being written by any path
OTHER than the guided dispatch's own "no" branch while guided.
mixed_baggage_pending was set. Fixed with three changes:

1. _guard_mixed_baggage_pending_write (new): runs immediately after the
   raw extractor merge, reverting flight.baggage/baggage_detail to
   whatever they were before the turn whenever mixed_baggage_pending was
   already set at the turn's start.
2. The two other general baggage-writing paths (_baggage_answer_by_meaning,
   _deterministic_baggage_facts) are skipped outright at their own call
   sites under the same condition.
3. _mixed_baggage_payment_time_hint no longer lets the yes/no question
   name or suggest a specific type (the original wording never did
   explicitly forbid it) - explicit instruction added.

zd10 (Linz): the customer said "no" (decline uniform choice now), תיק יד
בלבד (personal_item) was correctly saved, but Tinkerbell's own reply said
"טרולי לכולם" - a direct contradiction with the real saved value. Root
cause: the "no" path's hint only gave the upsell note ("a trolley or
suitcase can always be added"), which itself contains the word "טרולי" -
composing freely from that alone, Tinkerbell apparently restated it as the
choice just made. Fixed: the hint now states explicitly, before the
upsell note, that תיק יד בלבד was saved.

Run: python3 tools/qa_run9_zd9_zd10_mixed_baggage_live.py
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
            ("QA zd9 zd10", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def _post(message, history, trip_state, member_id):
    with client.session_transaction() as sess:
        sess["member_id"] = member_id
    r = client.post("/api/ariella/chat-clean", json={
        "message": message, "history": history, "trip_state": trip_state,
    })
    return r.get_json()


BILBAO_STATE = {
    "destination": {"places": ["בילבאו"], "mode": "specific", "status": "known"},
    "active_session": "flights",
    "requested_services": ["flights"],
    "session_status": {"flights": "active", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
    "dates": {"departure": "2027-03-10", "return": "2027-03-15"},
    "travelers": {"adults": 1, "children": 1},
}


def _fake_classifier_and_leaking_extractor(classifier_reply, extractor_baggage):
    """Simulates zd9's exact live shape: the general extractor (source=
    "state_extractor") returns a leaked flight.baggage fact in its own
    JSON (as if it read it from history/the same message), on the SAME
    turn the guided dispatch is reading the message as the yes/no answer
    (source="classifier")."""
    def _fake(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
        if source == "state_extractor":
            return json.dumps({
                "trip_update": {"flight": {"baggage": extractor_baggage}} if extractor_baggage else {},
                "restart_request": False, "restart_evidence": None,
                "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
                "link_request": False, "link_request_evidence": None,
            })
        if source == "classifier":
            return classifier_reply
        if source == "guided_extract":
            return json.dumps({"status": "other_topic", "field": None, "evidence": None})
        return "תשובה לדוגמה."
    return _fake


# =====================================================================
# zd9 (Bilbao): "yes" + the general extractor leaks flight.baggage from
# this same turn - nothing must be saved, the normal baggage question
# must be asked next, and the pending flag must clear.
# =====================================================================
member_zd9 = _make_member("qa-zd9-bilbao@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_classifier_and_leaking_extractor("true", ["checked_bag"])):
    state_zd9 = dict(BILBAO_STATE)
    state_zd9["guided"] = {
        "current_question": "baggage", "attempts": 0,
        "answered": ["dates", "travelers"], "mixed_baggage_pending": True,
    }
    r_zd9 = _post("נלך על מזוודה לכולם", [{"role": "assistant", "content": "האם לבחור כבודה אחידה אחת לכל הקבוצה כרגע?"}], state_zd9, member_zd9)
tu_zd9 = r_zd9.get("trip_update") or {}
check("zd9: nothing is saved despite the extractor leaking checked_bag "
      "this same turn - the 'yes' path never lets any general path write "
      "baggage while pending",
      not (tu_zd9.get("flight") or {}).get("baggage"))
check("zd9: pending flag cleared, baggage field stays open for the "
      "normal question next",
      not (tu_zd9.get("guided") or {}).get("mixed_baggage_pending")
      and (tu_zd9.get("guided") or {}).get("current_question") == "baggage")
check("zd9: the hint asks the normal 3-option baggage question",
      "תיק יד" in str(tu_zd9.get("_guided_ask_hint") or ""))

# Direct unit coverage of the new guard, isolated from the HTTP round-trip.
_prior_state = {"guided": {"mixed_baggage_pending": True}, "flight": {}}
_leaked_update = {"flight": {"baggage": ["checked_bag"]}, "guided": {"mixed_baggage_pending": True}}
_guarded = chat._guard_mixed_baggage_pending_write(_prior_state, _leaked_update)
check("_guard_mixed_baggage_pending_write: reverts a leaked baggage write "
      "back to nothing when mixed_baggage_pending was set at turn start",
      not (_guarded.get("flight") or {}).get("baggage"))
_prior_with_value = {"guided": {"mixed_baggage_pending": True}, "flight": {"baggage": ["personal_item"]}}
_unchanged_update = {"flight": {"baggage": ["checked_bag"]}, "guided": {"mixed_baggage_pending": True}}
_guarded2 = chat._guard_mixed_baggage_pending_write(_prior_with_value, _unchanged_update)
check("_guard_mixed_baggage_pending_write: reverts to the PRIOR real "
      "value (not just to empty) when one already existed",
      (_guarded2.get("flight") or {}).get("baggage") == ["personal_item"])
check("_guard_mixed_baggage_pending_write: a no-op when the flag was not "
      "set at turn start (never touches a normal turn)",
      chat._guard_mixed_baggage_pending_write(
          {"guided": {}, "flight": {}}, {"flight": {"baggage": ["checked_bag"]}},
      ).get("flight", {}).get("baggage") == ["checked_bag"])

# The two other general baggage paths must also be skipped outright while
# pending - not just reverted after the fact. Mock _baggage_answer_by_meaning
# itself to prove it's never even reached.
with patch.object(chat, "_baggage_answer_by_meaning", side_effect=AssertionError("must not be called while pending")):
    with patch.object(chat, "_post_claude", side_effect=_fake_classifier_and_leaking_extractor("true", None)):
        state_zd9b = dict(BILBAO_STATE)
        state_zd9b["guided"] = {
            "current_question": "baggage", "attempts": 0,
            "answered": ["dates", "travelers"], "mixed_baggage_pending": True,
        }
        r_zd9b = _post("בסדר, נבחר אחידה", [{"role": "assistant", "content": "שאלה על כבודה"}], state_zd9b, member_zd9)
check("zd9: _baggage_answer_by_meaning is skipped outright (never even "
      "called) while mixed_baggage_pending is set",
      (r_zd9b or {}).get("status") == "success")

# =====================================================================
# zd10 (Linz): "no" - personal_item is correctly saved, and the hint now
# states explicitly what was saved so Tinkerbell's own reply can't
# contradict it.
# =====================================================================
member_zd10 = _make_member("qa-zd10-linz@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_classifier_and_leaking_extractor("false", None)):
    state_zd10 = dict(BILBAO_STATE)
    state_zd10["guided"] = {
        "current_question": "baggage", "attempts": 0,
        "answered": ["dates", "travelers"], "mixed_baggage_pending": True,
    }
    r_zd10 = _post("לא, זה בסדר ככה", [{"role": "assistant", "content": "שאלה על כבודה"}], state_zd10, member_zd10)
tu_zd10 = r_zd10.get("trip_update") or {}
zd10_hint = str(tu_zd10.get("_guided_ask_hint") or "")
check("zd10: personal_item (תיק יד בלבד) is saved",
      (tu_zd10.get("flight") or {}).get("baggage") == ["personal_item"])
check("zd10 FIX: the hint explicitly states תיק יד בלבד was saved, so "
      "Tinkerbell's own composed reply can't contradict it the way it "
      "did live (\"טרולי לכולם\")",
      "נשמר תיק יד בלבד" in zd10_hint)

# =====================================================================
# Direct unit coverage of the revised payment-time hint: never names or
# suggests a specific baggage type in the yes/no question itself.
# =====================================================================
_payment_hint = chat._mixed_baggage_payment_time_hint()
check("_mixed_baggage_payment_time_hint (22.10 revision): explicitly "
      "forbids naming any specific type in the yes/no question",
      "לא מזכירה ולא מציעה שום סוג כבודה ספציפי" in _payment_hint)

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE email LIKE 'qa-zd%@example.com'")
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL ZD9/ZD10 MIXED-BAGGAGE LIVE-REGRESSION TESTS PASSED")
