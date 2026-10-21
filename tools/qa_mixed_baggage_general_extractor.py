"""QA for Shlomo's relay of Shaked's live stage-1 run-1 finding (20.10.2026,
b71506d, 1/5 - qa/reports/2026-10-20-stage1-live-run1.md on the shaked
branch), priority fix #2 of four blocking stage-1:

s1a2 (טביליסי, אמא ושתי בנות): "אני רק עם תיק יד, הבנות צריכות מזוודה" -
a mixed-per-passenger baggage request. The business owner's decision (20.10,
already implemented in PR #97's guided-extraction baggage branch -
_guided_field_update_and_confirm's mixed_per_passenger handling) says such a
request must resolve SILENTLY to the single highest tier (checked_bag),
never a per-passenger split. Live, it still saved
flight.baggage=['personal_item','checked_bag'] and replied listing a split
per passenger - the decision was never actually applied.

Root cause: the "mixed -> collapse to checked_bag" rule only ever existed in
the GUIDED-extraction baggage prompt (_guided_extract_answer's baggage
branch) - never in EXTRACTOR_SYSTEM (the general per-turn extraction call
that runs on EVERY turn regardless of guided dispatch) or in
_baggage_answer_by_meaning (a second, separate single-value classifier that
also runs unconditionally whenever flight.baggage is still empty after a
baggage question). Whichever of these two paths actually captured this
particular exchange (guided dispatch not engaging that turn for any reason,
or its own classification simply missing this phrasing), neither general
path had any concept of "mixed request" at all - EXTRACTOR_SYSTEM's own
baggage instruction would happily record BOTH "תיק יד" (personal_item) AND
"מזוודה" (checked_bag) as if they were both meant for the whole group,
since from a naive literal read, both items genuinely were mentioned in the
message - exactly matching the live finding.

Both now carry the same semantic instruction the guided prompt already had:
a booking is always one uniform choice for the whole group, so a mixed
request collapses to checked_bag rather than being recorded as a
multi-type list. This is a pure prompt/understanding fix (the model decides
meaning, never a phrase list) - verified by asserting the instruction text
is present, and by simulating a model that already follows it correctly to
confirm the downstream merge produces the right final state.

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
# "mixed -> collapse to checked_bag" instruction the guided prompt already
# had, so neither one independently records a naive multi-type split.
# =====================================================================
check("EXTRACTOR_SYSTEM (the general per-turn extraction prompt, runs every "
      "turn regardless of guided dispatch) now teaches the same "
      "mixed-per-passenger -> checked_bag collapsing rule",
      "הזמנה היא תמיד כבודה אחידה אחת לכל הכרטיסים" in chat.EXTRACTOR_SYSTEM
      and 'flight.baggage=["checked_bag"]' in chat.EXTRACTOR_SYSTEM)
check("EXTRACTOR_SYSTEM explicitly still allows a genuinely uniform "
      "multi-item request for the whole group (e.g. 'טרולי וגם מזוודה "
      "לכולנו') to be saved as-is - this is not the same as a mixed "
      "per-passenger split",
      "טרולי וגם מזוודה לכולנו" in chat.EXTRACTOR_SYSTEM)

_baggage_meaning_src = __import__("inspect").getsource(chat._baggage_answer_by_meaning)
check("_baggage_answer_by_meaning (the second, separate single-value "
      "baggage classifier that runs whenever flight.baggage is still "
      "empty) also now understands a mixed-per-passenger request and "
      "resolves it to checked_bag",
      "כבודה אחידה אחת לכל הכרטיסים" in _baggage_meaning_src
      and "בקשה מעורבת" in _baggage_meaning_src)

# =====================================================================
# End-to-end simulation: a model that already follows the new instruction
# correctly (mocked to return checked_bag for s1a2's exact mixed phrasing)
# must have its result actually persisted as the uniform, single-type
# resolution - proving the merge pipeline doesn't lose or override it.
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
        # instruction: a mixed request collapses to checked_bag, never a
        # naive multi-type list.
        return json.dumps({
            "trip_update": {"flight": {"baggage": ["checked_bag"]}},
            "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
            "link_request": False, "link_request_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "מצוין, קלטתי את הכבודה."
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
check("s1a2's exact live mixed-baggage message resolves to a single uniform "
      "checked_bag, never a multi-type personal_item+checked_bag split",
      final_baggage == ["checked_bag"])

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL MIXED-BAGGAGE-GENERAL-EXTRACTOR TESTS PASSED")
