"""QA for the two GENERAL (non-guided) baggage paths' handling of a mixed
per-passenger request - EXTRACTOR_SYSTEM (the per-turn extraction prompt
that runs on EVERY turn regardless of guided dispatch) and
_baggage_answer_by_meaning (a second, separate single-value classifier
that also runs unconditionally whenever flight.baggage is still empty
after a baggage question).

History: Shlomo's relay of Shaked's live stage-1 run-1 finding (20.10.2026,
b71506d, 1/5 - qa/reports/2026-10-20-stage1-live-run1.md on the shaked
branch): s1a2 (טביליסי, אמא ושתי בנות) - "אני רק עם תיק יד, הבנות צריכות
מזוודה" - a mixed-per-passenger request that EXTRACTOR_SYSTEM naively
recorded as flight.baggage=['personal_item','checked_bag'], as if both
items were meant for the whole group. The fix at the time (per the 20.10
business-owner directive) taught both general paths the same "mixed ->
collapse to checked_bag" rule the guided-extraction baggage prompt already
had.

FINAL business-owner decision (22.10.2026, 4th and final revision, relayed
by Shlomo), fully superseding that 20.10 design after Shaked rejected it
(the real bug class, run-7 bug B, Phuket): resolving a mixed request to
checked_bag was itself wrong - no value should ever be silently chosen.
A mixed per-passenger request is never saved by EITHER general path either
- flight.baggage is left exactly as it was, and the real handling (explain
that different baggage per passenger can only be added at the payment
stage, then ask yes/no whether to choose one uniform baggage for the
group) happens only through the guided-extraction flow (see
_mixed_baggage_payment_time_hint and tools/qa_guided_extraction_baggage_
014a.py's scenario 2c). This file keeps the same s1a2 end-to-end repro,
updated to assert the new no-save behavior instead.

Run: python3 tools/qa_mixed_baggage_general_extractor.py
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


# =====================================================================
# Prompt-text coverage: both general-extraction paths now carry the same
# "mixed -> never resolve, never save" instruction - neither one
# independently records a naive multi-type split OR a silent single-value
# resolution any more.
# =====================================================================
check("EXTRACTOR_SYSTEM (the general per-turn extraction prompt, runs every "
      "turn regardless of guided dispatch) now teaches the mixed-"
      "per-passenger request is never resolved or saved here at all",
      "הזמנה היא תמיד כבודה אחידה אחת לכל הכרטיסים" in chat.EXTRACTOR_SYSTEM
      and "לא נפתרת ולא נשמרת כלל כאן" in chat.EXTRACTOR_SYSTEM)
check("EXTRACTOR_SYSTEM no longer tells the model to collapse a mixed "
      "request to checked_bag itself",
      'flight.baggage=["checked_bag"]' not in chat.EXTRACTOR_SYSTEM)
check("EXTRACTOR_SYSTEM explicitly still allows a genuinely uniform "
      "multi-item request for the whole group (e.g. 'טרולי וגם מזוודה "
      "לכולנו') to be saved as-is - this is not the same as a mixed "
      "per-passenger split",
      "טרולי וגם מזוודה לכולנו" in chat.EXTRACTOR_SYSTEM)

_baggage_meaning_src = __import__("inspect").getsource(chat._baggage_answer_by_meaning)
check("_baggage_answer_by_meaning (the second, separate single-value "
      "baggage classifier that runs whenever flight.baggage is still "
      "empty) also now returns null (no save) for a mixed-per-passenger "
      "request, never collapsing it to checked_bag itself",
      "בקשה מעורבת" in _baggage_meaning_src
      and 'checked_bag"' not in _baggage_meaning_src.split("בקשה מעורבת")[1].split("\\n")[0])

# =====================================================================
# End-to-end simulation: a model that already follows the new instruction
# correctly (mocked to leave flight.baggage untouched for s1a2's exact
# mixed phrasing) must result in NOTHING being saved for baggage this
# turn - proving the merge pipeline doesn't invent or default a value.
# =====================================================================
def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports,gender) "
            "VALUES(?,?,?,?,?,?,?,?)",
            ("QA Mixed Baggage", email, generate_password_hash("Test1234!"),
             datetime.now(timezone.utc).isoformat(), "active", 0, "[]", "female"),
        )
        return cur.lastrowid


member = _make_member("qa-mixed-baggage@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member

_S1A2_MESSAGE = "אני רק עם תיק יד, הבנות צריכות מזוודה"


def _quiet_post_claude(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        # Simulates the general extractor having correctly learned the new
        # instruction: a mixed request is left entirely unresolved here,
        # never collapsed to any single value.
        return json.dumps({
            "trip_update": {},
            "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
            "link_request": False, "link_request_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "classifier":
        # _baggage_answer_by_meaning's own call - also returns null for a
        # mixed request per the updated prompt.
        return json.dumps({"baggage": None})
    if source == "tinkerbell_reply":
        return "מצוין, קלטתי."
    return "{}"


base_state = {
    "trip_type": "standard",
    "destination": {"places": ["טביליסי"], "mode": "specific", "status": "known"},
    "destination_airports": ["TBS"],
    "departure_airport": "TLV",
    "travelers": {"adults": 1, "children": 2, "child_ages": [10, 12]},
    "dates": {"departure": "2027-04-05", "return": "2027-04-10", "needs_confirmation": False},
    "flight": {"connection_preference": "any", "cabin": "economy", "baggage": []},
    "requested_services": ["flights"],
    "service_decisions": {"flights": {"wanted": True}},
    "session_status": {"flights": "active", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
    "active_session": "flights",
}

with patch.object(chat, "_post_claude", side_effect=_quiet_post_claude):
    r = client.post("/api/ariella/chat-clean", json={
        "message": _S1A2_MESSAGE,
        "history": [{"role": "assistant", "content": "איזו כבודה תצטרכו?"}],
        "trip_state": base_state,
    })
data = r.get_json() or {}
final_baggage = ((data.get("trip_update") or {}).get("flight") or {}).get("baggage")
check("s1a2's exact live mixed-baggage message: nothing is saved for "
      "baggage by the general extraction paths - never a silent "
      "single-value resolution, never a naive multi-type split",
      not final_baggage)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL MIXED-BAGGAGE-GENERAL-EXTRACTOR TESTS PASSED")
