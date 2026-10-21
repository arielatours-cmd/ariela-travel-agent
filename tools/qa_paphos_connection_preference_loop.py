"""QA for Shlomo's relay of the business owner's stage-1 run-5 finding
(Paphos): "חשוב לכם שהטיסה תהיה ישירה?" was asked and answered "לא חובה"
(not required) - connection_preference stayed null, and the identical
question repeated roughly 28 times in a row. The guided-extraction loop
guard never engaged (attempts stayed 0) since connection_preference isn't
a guided field at all.

Two independent root causes, both fixed here:

1. EXTRACTOR_SYSTEM's own instruction for flight.connection_preference
   told the model to leave the field null both when the question was
   never asked AND when the customer explicitly answered with
   indifference - conflating "not yet asked" with "asked and answered
   'doesn't matter'". Fixed: the instruction now explicitly distinguishes
   the two and instructs the model, from genuine understanding (never a
   fixed phrase list), to write the literal string "אין העדפה" once the
   customer's answer - in ANY real phrasing ("לא חובה", "לא משנה",
   "גם עם עצירה זה בסדר", a bare "לא", etc.) - expresses that a direct
   flight isn't actually important to them.

2. There was no general defense against repeating an identical fixed
   question forever OUTSIDE the guided-extraction flow - only guided
   fields had a loop guard (#122, Copenhagen). _apply_gap_repeat_guard is
   a parallel, general mechanism: when the same canonical gap-question was
   asked in each of the last two assistant turns and the gap is STILL
   open, the third ask never repeats the identical text again - an
   OPTIONAL preference-type gap (today, only flight.connection_preference)
   gets its honest "אין העדפה" default written directly, closing it
   silently; any other (required) gap instead gets a one-turn hint telling
   Tinkerbell to rephrase with concrete examples, never the same text a
   third time.

Run: python3 tools/qa_paphos_connection_preference_loop.py
"""
import os
import sys
import json
import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

import ariella_chat_clean as chat
import whatsapp_bridge
from werkzeug.security import generate_password_hash

DB = database.DB_PATH
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
            ("QA Paphos", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


# =====================================================================
# 1. EXTRACTOR_SYSTEM's own instruction now distinguishes null (never
# asked) from "אין העדפה" (asked and answered with indifference), and
# teaches the model to understand ANY real phrasing of that indifference
# - never a fixed phrase list.
# =====================================================================
check("EXTRACTOR_SYSTEM explicitly names the null-vs-'אין העדפה' distinction",
      "null פירושו" in chat.EXTRACTOR_SYSTEM and "אין העדפה\" פירושו" in chat.EXTRACTOR_SYSTEM)
check("EXTRACTOR_SYSTEM gives exactly the live Paphos phrasing ('לא חובה') "
      "as a single illustrative example, not a list of phrasings",
      "לא חובה" in chat.EXTRACTOR_SYSTEM)
check("the instruction explicitly says this must come from understanding "
      "the context of the conversation, not a fixed word list",
      "מרשימת ביטויים קבועה" in chat.EXTRACTOR_SYSTEM)
check("per the business owner's explicit decision (21.10.2026): no closed "
      "list of phrasings in the prompt itself - other real-transcript "
      "synonyms ('לא משנה לי', 'קונקשן בסדר', 'גם עם עצירה') are "
      "deliberately NOT enumerated alongside the one example given",
      not any(
          phrase in chat.EXTRACTOR_SYSTEM
          for phrase in ("לא משנה לי", "קונקשן בסדר", "גם עם עצירה")
      ))

# =====================================================================
# 2. Direct unit tests of _apply_gap_repeat_guard - the general, non-
# guided loop guard.
# =====================================================================
_DIRECT_Q = "חשוב לכם שהטיסה תהיה ישירה?"

with patch.object(chat, "_session_gaps", return_value=["flight.connection_preference"]):
    _history_two_repeats = [
        {"role": "assistant", "content": _DIRECT_Q},
        {"role": "user", "content": "לא חובה"},
        {"role": "assistant", "content": _DIRECT_Q},
        {"role": "user", "content": "לא משנה לנו"},
    ]
    _result_optional = chat._apply_gap_repeat_guard(
        {"active_session": "flights", "flight": {"baggage": ["checked_bag"]}},
        _history_two_repeats, "flights",
    )
check("after the SAME fixed question was asked twice in a row and is "
      "still unresolved, the OPTIONAL connection_preference gap gets its "
      "honest 'אין העדפה' default written directly",
      _result_optional.get("flight", {}).get("connection_preference") == "אין העדפה")
check("the default-write never disturbs an unrelated field already in "
      "the same section (baggage stays untouched)",
      _result_optional.get("flight", {}).get("baggage") == ["checked_bag"])

with patch.object(chat, "_session_gaps", return_value=["flight.connection_preference"]):
    _history_one_repeat = [
        {"role": "assistant", "content": _DIRECT_Q},
        {"role": "user", "content": "לא חובה"},
    ]
    _result_too_early = chat._apply_gap_repeat_guard(
        {"active_session": "flights"}, _history_one_repeat, "flights",
    )
check("regression: with only ONE prior ask (not yet twice in a row), the "
      "guard never fires - genuinely needs two unresolved repeats first",
      "connection_preference" not in _result_too_early.get("flight", {}))

_LODGING_Q = chat._GAP_QUESTION_TEXT["lodging.details.type"]
with patch.object(chat, "_session_gaps", return_value=["lodging.details.type"]):
    _history_lodging = [
        {"role": "assistant", "content": _LODGING_Q},
        {"role": "user", "content": "עדיין לא בטוחים"},
        {"role": "assistant", "content": _LODGING_Q},
        {"role": "user", "content": "לא יודעת עדיין"},
    ]
    _result_required = chat._apply_gap_repeat_guard(
        {"active_session": "lodging"}, _history_lodging, "lodging",
    )
check("a REQUIRED (non-optional) gap asked twice unresolved never gets a "
      "silent default - it gets a rephrase-with-examples hint instead",
      _LODGING_Q in str(_result_required.get("_gap_repeat_rephrase_hint") or "")
      and "דוגמאות" in str(_result_required.get("_gap_repeat_rephrase_hint") or ""))

with patch.object(chat, "_session_gaps", return_value=["lodging.details.type"]):
    _result_no_repeat = chat._apply_gap_repeat_guard(
        {"active_session": "lodging"},
        [{"role": "assistant", "content": "שלום, בוא נתחיל"}],
        "lodging",
    )
check("regression: an unrelated assistant history (never asked this "
      "question at all) never triggers either branch",
      "_gap_repeat_rephrase_hint" not in _result_no_repeat
      and "lodging" not in _result_no_repeat)

check("the guard is a pure no-op once gaps is already empty (field resolved)",
      chat._apply_gap_repeat_guard(
          {"active_session": "flights"},
          [{"role": "assistant", "content": _DIRECT_Q}, {"role": "user", "content": "לא חובה"}] * 2,
          "flights",
      ) == {"active_session": "flights"})

# =====================================================================
# 3. End-to-end reproduction of the exact Paphos shape via whatsapp_
# bridge.ariella_turn: the customer answers the direct-flight question
# with "לא חובה" - with a correctly-behaving (post prompt-fix) extractor,
# this is understood immediately and the field closes in ONE turn, never
# needing the loop guard at all.
# =====================================================================
_PAPHOS_STATE = {
    "destination": {"places": ["פאפוס"], "mode": "specific", "status": "known"},
    "destination_airports": ["PFO"],
    "departure_airport": "TLV",
    "travelers": {"adults": 2},
    "dates": {"departure": "2027-05-05", "return": "2027-05-10", "needs_confirmation": False},
    "budget_per_person": {"amount": 500, "currency": "ILS"},
    "flight": {"baggage": ["checked_bag"]},
    "requested_services": ["flights"],
    "service_decisions": {"flights": {"wanted": True}},
    "session_status": {"flights": "active", "lodging": "pending", "car": "pending", "trip_planning": "pending"},
    "active_session": "flights",
    "trip_type": "standard",
}


def _mock_understood_correctly(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        # Simulates the extractor correctly understanding "לא חובה" per the
        # strengthened prompt instruction - genuine understanding, not a
        # phrase match performed by this test itself.
        return json.dumps({
            "trip_update": {"flight": {"connection_preference": "אין העדפה"}},
            "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "מעולה, סגרנו את זה. איזו כבודה תרצו לקחת?"
    return "{}"


m_paphos = _make_member("qa-paphos-direct@example.com")
database.save_ariella_conversation(m_paphos, [
    {"role": "user", "content": "פאפוס, זוג, 5.5 עד 10.5.2027"},
    {"role": "assistant", "content": "קלטתי - פאפוס. " + _DIRECT_Q},
], dict(_PAPHOS_STATE))

with patch.object(chat, "_post_claude", side_effect=_mock_understood_correctly):
    whatsapp_bridge.ariella_turn(m_paphos, "לא חובה")

_state_after = (database.load_ariella_conversation(m_paphos) or {}).get("trip_state") or {}
check("the exact Paphos answer ('לא חובה') resolves connection_preference "
      "to 'אין העדפה' in ONE turn, through the real extraction pipeline - "
      "the field is never left null after being genuinely answered",
      (_state_after.get("flight") or {}).get("connection_preference") == "אין העדפה")

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL PAPHOS-CONNECTION-PREFERENCE-LOOP TESTS PASSED")
