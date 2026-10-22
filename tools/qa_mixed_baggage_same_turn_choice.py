"""QA for the "same-turn choice" follow-up to PR #133's zd9/zd10 fix
(relayed by Shlomo, 22.10.2026, right after Shaked approved #133):

Problem: _guard_mixed_baggage_pending_write (PR #133) unconditionally
reverted flight.baggage/baggage_detail whenever guided.mixed_baggage_pending
was set at the turn's start - correct for zd9 (nothing must be guessed from
an unverified extractor write), but it also threw away a type the customer
had genuinely just named in the SAME breath as "yes" ("כן, מזוודה לכולם"),
forcing a redundant re-ask of the normal baggage question right after "yes".

Fix (exact business-owner wording, relayed by Shlomo): if the yes/no
classifier reads "yes" AND the general extractor wrote exactly one baggage
type with a genuine flight.baggage_detail_evidence quote from the CURRENT
message (word-for-word, not a leak from earlier history), save that value
directly instead of discarding and re-asking. A bare "yes" alone (no
same-breath type, so no evidence) must keep behaving exactly as before
(PR #133's own re-ask). Implemented via:

1. EXTRACTOR_SYSTEM prompt: now also fills flight.baggage_detail_evidence
   (the same field it already used for baggage_detail) whenever it writes a
   single uniform type in direct reply to the pending yes/no question.
2. _guard_mixed_baggage_pending_write: before reverting, stashes a single
   evidenced type in the transient trip_update["_mixed_baggage_evidenced_
   type"] key (never persisted) instead of discarding it outright.
3. _handle_guided_extraction_turn's "yes" branch: pops that transient key
   and, only once ITS OWN classifier call independently confirms "yes",
   saves the type directly and advances past "baggage" instead of asking
   again.

Run: python3 tools/qa_mixed_baggage_same_turn_choice.py
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
            ("QA same-turn choice", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def _post(message, history, trip_state, member_id):
    with client.session_transaction() as sess:
        sess["member_id"] = member_id
    r = client.post("/api/ariella/chat-clean", json={
        "message": message, "history": history, "trip_state": trip_state,
    })
    return r.get_json()


BASE_STATE = {
    "destination": {"places": ["בילבאו"], "mode": "specific", "status": "known"},
    "active_session": "flights",
    "requested_services": ["flights"],
    "session_status": {"flights": "active", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
    "dates": {"departure": "2027-03-10", "return": "2027-03-15"},
    "travelers": {"adults": 1, "children": 1},
}


def _fake_turn(classifier_reply, extractor_baggage=None, extractor_evidence=None):
    """Mirrors tools/qa_run9_zd9_zd10_mixed_baggage_live.py's helper, extended
    with baggage_detail_evidence so the general extractor's JSON can carry a
    genuine (or absent/non-matching) same-breath quote."""
    def _fake(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
        if source == "state_extractor":
            flight_fragment = {}
            if extractor_baggage is not None:
                flight_fragment["baggage"] = extractor_baggage
            if extractor_evidence is not None:
                flight_fragment["baggage_detail_evidence"] = extractor_evidence
            return json.dumps({
                "trip_update": {"flight": flight_fragment} if flight_fragment else {},
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


def _pending_state():
    state = dict(BASE_STATE)
    state["guided"] = {
        "current_question": "baggage", "attempts": 0,
        "answered": ["dates", "travelers"], "mixed_baggage_pending": True,
    }
    return state


ASSISTANT_QUESTION = [{"role": "assistant", "content": "האם לבחור כבודה אחידה אחת לכל הקבוצה כרגע?"}]

# =====================================================================
# 1. "yes" + the same-breath type, with a genuine verbatim quote from
#    THIS message - must be saved directly, no redundant re-ask.
# =====================================================================
member1 = _make_member("qa-same-turn-1@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_turn("true", ["checked_bag"], "מזוודה")):
    r1 = _post("כן, מזוודה לכולם", ASSISTANT_QUESTION, _pending_state(), member1)
tu1 = r1.get("trip_update") or {}
check("1. yes+evidenced type: flight.baggage is saved directly as checked_bag",
      (tu1.get("flight") or {}).get("baggage") == ["checked_bag"])
check("1. yes+evidenced type: pending flag cleared",
      not (tu1.get("guided") or {}).get("mixed_baggage_pending"))
check("1. yes+evidenced type: baggage marked answered (no redundant re-ask of it)",
      "baggage" in ((tu1.get("guided") or {}).get("answered") or []))
check("1. yes+evidenced type: the transient evidence key never leaks into state",
      "_mixed_baggage_evidenced_type" not in tu1 and "_mixed_baggage_evidenced_type" not in (tu1.get("flight") or {}))
check("1. yes+evidenced type: the hint does not ask the normal 3-option baggage "
      "question again (no redundant re-ask)",
      "תיק יד בלבד, רק טרולי" not in str(tu1.get("_guided_ask_hint") or "")
      and "איזו כבודה" not in str(tu1.get("_guided_ask_hint") or ""))
# Dry-run 3 (Shaked, 22.10.2026, case A): the reply claimed "מזוודה בבטן
# המטוס" (checked_bag) while the real saved value was a trolley
# (carry_on_only) - the exact same composition-drift class as zd10 (the
# upsell note's own mention of other tiers gave Tinkerbell words to
# misremember as the choice just made), but in this "yes + same-breath
# type" branch, which never got zd10's explicit-statement fix.
check("1. yes+evidenced type (dry-run 3 FIX): the hint explicitly states, "
      "by name, exactly what WAS saved, before any upsell note - never "
      "leaving Tinkerbell to recall/invent which type was chosen",
      "נשמר" in str(tu1.get("_guided_ask_hint") or "")
      and chat._BAGGAGE_HE.get("checked_bag", "checked_bag") in str(tu1.get("_guided_ask_hint") or ""))

# =====================================================================
# 2. Bare "yes" alone, no same-breath type at all - must behave exactly
#    as PR #133 already fixed: nothing saved yet, normal question re-asked.
# =====================================================================
member2 = _make_member("qa-same-turn-2@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_turn("true", None, None)):
    r2 = _post("כן, בסדר", ASSISTANT_QUESTION, _pending_state(), member2)
tu2 = r2.get("trip_update") or {}
check("2. bare yes alone: nothing saved yet (unchanged PR #133 behavior)",
      not (tu2.get("flight") or {}).get("baggage"))
check("2. bare yes alone: pending flag cleared, baggage stays open for the "
      "normal question next",
      not (tu2.get("guided") or {}).get("mixed_baggage_pending")
      and (tu2.get("guided") or {}).get("current_question") == "baggage")

# =====================================================================
# 3. "yes" + a type, but the "evidence" the extractor supplied is NOT a
#    genuine quote from this message (fabricated/leaked) - must NOT be
#    trusted; falls through to the normal re-ask, exactly like bare yes.
# =====================================================================
member3 = _make_member("qa-same-turn-3@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_turn("true", ["checked_bag"], "משהו שלא נאמר בהודעה")):
    r3 = _post("כן", ASSISTANT_QUESTION, _pending_state(), member3)
tu3 = r3.get("trip_update") or {}
check("3. yes + fabricated/non-matching evidence: never trusted - nothing saved",
      not (tu3.get("flight") or {}).get("baggage"))
check("3. yes + fabricated/non-matching evidence: falls through to the normal "
      "re-ask, exactly like a bare yes",
      (tu3.get("guided") or {}).get("current_question") == "baggage"
      and not (tu3.get("guided") or {}).get("mixed_baggage_pending"))

# =====================================================================
# 4. "yes" + TWO types in the same breath (still ambiguous/ill-defined,
#    not a single clear choice) - must NOT be auto-saved either.
# =====================================================================
member4 = _make_member("qa-same-turn-4@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_turn("true", ["checked_bag", "carry_on_only"], "מזוודה וטרולי")):
    r4 = _post("כן, מזוודה וטרולי לכולם", ASSISTANT_QUESTION, _pending_state(), member4)
tu4 = r4.get("trip_update") or {}
check("4. yes + two same-breath types: not auto-saved (only a single clear "
      "type qualifies) - falls through to the normal re-ask",
      not (tu4.get("flight") or {}).get("baggage")
      and (tu4.get("guided") or {}).get("current_question") == "baggage")

# =====================================================================
# 5. "no" + a same-breath type-ish word still saves personal_item exactly
#    like PR #133 already fixed - the evidenced-type path is a "yes"-only
#    branch and must never interfere with "no".
# =====================================================================
member5 = _make_member("qa-same-turn-5@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_turn("false", ["checked_bag"], "מזוודה")):
    r5 = _post("לא, זה בסדר ככה", ASSISTANT_QUESTION, _pending_state(), member5)
tu5 = r5.get("trip_update") or {}
check("5. no (even with a same-breath evidenced type present): personal_item "
      "is still saved, unaffected by the new yes-only path",
      (tu5.get("flight") or {}).get("baggage") == ["personal_item"])

# =====================================================================
# Direct unit coverage of _guard_mixed_baggage_pending_write's new
# evidenced-stash behavior, isolated from the HTTP round-trip.
# =====================================================================
_prior = {"guided": {"mixed_baggage_pending": True}, "flight": {}}

_single_evidenced = {"flight": {"baggage": ["checked_bag"], "baggage_detail_evidence": "מזוודה"}}
_g1 = chat._guard_mixed_baggage_pending_write(_prior, dict(_single_evidenced), "כן, מזוודה לכולם")
check("unit: single type + genuine verbatim evidence -> stashed in the "
      "transient key",
      _g1.get("_mixed_baggage_evidenced_type") == "checked_bag")
check("unit: the real flight.baggage is still reverted (not trusted blindly "
      "at this layer - only the guided dispatch's own yes/no call decides)",
      not (_g1.get("flight") or {}).get("baggage"))

_single_no_evidence = {"flight": {"baggage": ["checked_bag"], "baggage_detail_evidence": None}}
_g2 = chat._guard_mixed_baggage_pending_write(_prior, dict(_single_no_evidence), "כן")
check("unit: single type with no evidence at all -> nothing stashed",
      "_mixed_baggage_evidenced_type" not in _g2)

_single_bad_evidence = {"flight": {"baggage": ["checked_bag"], "baggage_detail_evidence": "לא נאמר כזה דבר"}}
_g3 = chat._guard_mixed_baggage_pending_write(_prior, dict(_single_bad_evidence), "כן")
check("unit: single type with a non-matching/fabricated quote -> nothing "
      "stashed",
      "_mixed_baggage_evidenced_type" not in _g3)

_two_types = {"flight": {"baggage": ["checked_bag", "carry_on_only"], "baggage_detail_evidence": "מזוודה וטרולי"}}
_g4 = chat._guard_mixed_baggage_pending_write(_prior, dict(_two_types), "כן, מזוודה וטרולי")
check("unit: two types in the same write -> nothing stashed (only a single "
      "clear type qualifies)",
      "_mixed_baggage_evidenced_type" not in _g4)

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE email LIKE 'qa-same-turn-%@example.com'")
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL MIXED-BAGGAGE SAME-TURN-CHOICE TESTS PASSED")
