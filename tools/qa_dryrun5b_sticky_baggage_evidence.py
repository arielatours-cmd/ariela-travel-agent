"""QA for dry-run 5b item 3 (Shlomo/Shaked, 22.10.2026, qa-dryrun branch,
qa/reports/2026-10-22-dryrun5b.md, scenario A, turn 9): a plain "יש לנו"
answering an unrelated LODGING yes/no question silently flipped
flight.baggage from ["personal_item"] to ["carry_on_only"] - the customer
said nothing about baggage at all that turn. The explanation Ariella then
gave also reversed which traveler was assigned which bag type (a separate
symptom of the same underlying silent-overwrite bug: once the wrong value
is in state, any wording built from it is wrong too).

Root cause (confirmed via grep): _guard_destination_change_evidence already
exists to lock destination/destination_airports against exactly this class
of bug (an extractor claim with no genuine evidence from the CURRENT
message), but no equivalent guard existed for flight.baggage - the main
per-turn extractor was free to rewrite it on ANY turn, evidence or not.

Fixed, mirroring the destination guard's exact pattern:
- A new baggage_evidence top-level JSON sibling of trip_update (alongside
  destination_evidence/dates_evidence/restart_evidence), required by
  EXTRACTOR_SYSTEM's own prompt whenever flight.baggage is already set and
  the model writes a different value.
- _guard_baggage_change_evidence: once flight.baggage is non-empty in
  state, a differing claimed value is accepted only with a verbatim quote
  (baggage_evidence) genuinely present in the customer's current message -
  otherwise it reverts to the prior, already-settled value. Wired into the
  same guard chain immediately after _guard_destination_change_evidence.
- A new "baggage_change" diagnostic event (structured before/after values
  only - the closed baggage-type list, never the customer's free text).

Never touches flight.baggage_detail/baggage_detail_evidence - those already
have their own separate guard (_validate_baggage_detail_against_message),
unaffected by this change.

Run: python3 tools/qa_dryrun5b_sticky_baggage_evidence.py
"""
import os
import sys
import json
import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import database
database.init_db()

import ariella_chat_clean as chat
import whatsapp_bridge
import ai_usage
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
            ("QA Dryrun5b StickyBaggage", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


# =====================================================================
# Schema/registration checks.
# =====================================================================
check("baggage_change registered as a valid diagnostic event source",
      "baggage_change" in ai_usage.DIAGNOSTIC_EVENT_SOURCES)
check("EXTRACTOR_SYSTEM documents baggage_evidence as a top-level sibling of trip_update",
      '"baggage_evidence"' in chat.EXTRACTOR_SYSTEM)
check("baggage_evidence is schema-ordered before trip_update (truncation-safe)",
      chat.EXTRACTOR_SYSTEM.index('"baggage_evidence"') < chat.EXTRACTOR_SYSTEM.index('"trip_update"'))


# =====================================================================
# Direct unit tests of the guard function itself.
# =====================================================================
_state_personal_item = {"flight": {"baggage": ["personal_item"]}}

# The exact dr5b scenario A repro: extractor claims carry_on_only with no
# evidence, answering an unrelated lodging yes/no question.
_claimed_carry_on = {"flight": {"baggage": ["carry_on_only"]}}
_locked = chat._guard_baggage_change_evidence(_state_personal_item, dict(_claimed_carry_on), None, "יש לנו")
check("scenario A repro: an ungrounded flight.baggage replacement (no evidence quote) is reverted to the prior value",
      _locked.get("flight", {}).get("baggage") == ["personal_item"])

# A genuine quoted baggage change is accepted, not reverted.
_claimed_checked = {"flight": {"baggage": ["checked_bag"]}}
_accepted = chat._guard_baggage_change_evidence(
    _state_personal_item, dict(_claimed_checked), "בעצם נצטרך מזוודה", "רגע, בעצם נצטרך מזוודה בבטן המטוס"
)
check("a genuinely quoted baggage change is accepted, not reverted",
      _accepted.get("flight", {}).get("baggage") == ["checked_bag"])

# Regression: the FIRST time baggage is set (nothing to protect yet).
_no_prior_state = {"flight": {"baggage": []}}
_first_time = chat._guard_baggage_change_evidence(_no_prior_state, dict(_claimed_checked), None, "מזוודה")
check("regression: the FIRST time flight.baggage is set (nothing to protect yet) is never blocked",
      _first_time.get("flight", {}).get("baggage") == ["checked_bag"])

# Regression: an unchanged value is left alone (and never requires evidence).
_unchanged = chat._guard_baggage_change_evidence(_state_personal_item, {"flight": {"baggage": ["personal_item"]}}, None, "יש לנו")
check("regression: an unchanged flight.baggage value is passed through with no evidence required",
      _unchanged.get("flight", {}).get("baggage") == ["personal_item"])

# Regression: baggage_detail/baggage_detail_evidence are never touched by this guard.
_with_detail = chat._guard_baggage_change_evidence(
    _state_personal_item,
    dict(_claimed_carry_on, flight={"baggage": ["carry_on_only"], "baggage_detail": {"checked_bag": 1}, "baggage_detail_evidence": "משהו"}),
    None, "יש לנו",
)
check("regression: this guard only reverts baggage, never baggage_detail/baggage_detail_evidence",
      _with_detail.get("flight", {}).get("baggage") == ["personal_item"]
      and _with_detail.get("flight", {}).get("baggage_detail") == {"checked_bag": 1}
      and _with_detail.get("flight", {}).get("baggage_detail_evidence") == "משהו")


# =====================================================================
# End-to-end through the real pipeline (scenario A, turn 9 shape).
# =====================================================================
m_baggage = _make_member("qa-dryrun5b-sticky-baggage@example.com")
baggage_state = {
    "destination": {"places": ["פאפוס"], "mode": "specific", "status": "known"},
    "destination_airports": ["PFO"],
    "travelers": {"adults": 2},
    "dates": {"departure": "2027-06-10", "return": "2027-06-17", "needs_confirmation": False},
    "requested_services": ["flights", "lodging"],
    "service_decisions": {"flights": {"wanted": True}, "lodging": {"wanted": True}},
    "flight": {"baggage": ["personal_item"]},
    "lodging": {"interested": "unknown", "details": {}},
    "session_status": {"flights": "active", "lodging": "pending", "car": "pending", "trip_planning": "pending"},
    "active_session": "flights",
}
database.save_ariella_conversation(m_baggage, [
    {"role": "user", "content": "פאפוס, זוג, 10-17 ביוני 2027, תיק יד בלבד"},
    {"role": "assistant", "content": "קלטתי. יש לכם כבר לינה מסודרת, או שתרצו שאעזור?"},
], dict(baggage_state))


def _fake_post_claude_baggage(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {"flight": {"baggage": ["carry_on_only"]}, "lodging": {"interested": "yes", "details": {}}},
            "restart_request": False, "restart_evidence": None, "dates_evidence": None,
            "destination_evidence": None, "baggage_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "מעולה, אעזור עם הלינה. תשובה לדוגמה."
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_baggage):
    whatsapp_bridge.ariella_turn(m_baggage, "יש לנו")
_state_after = (database.load_ariella_conversation(m_baggage) or {}).get("trip_state") or {}
check("scenario A end-to-end: an ungrounded extractor claim never actually overwrites flight.baggage live",
      _state_after.get("flight", {}).get("baggage") == ["personal_item"])
_baggage_rows = [
    r for r in ai_usage.diagnostic_rows("baggage_change", include_test=True)
    if r.get("member_id") == m_baggage
]
check("a baggage_change diagnostic row was written for the blocked attempt",
      bool(_baggage_rows) and json.loads(_baggage_rows[0]["details"]).get("verified") is False)
check("no diagnostic row anywhere contains the customer's own message text",
      all("יש לנו" != (r.get("details") or "") for r in _baggage_rows))

# Regression: an ordinary turn where flight.baggage is untouched must never
# write a spurious diagnostic row.
m_baggage_quiet = _make_member("qa-dryrun5b-sticky-baggage-quiet@example.com")
database.save_ariella_conversation(m_baggage_quiet, [
    {"role": "user", "content": "פאפוס, זוג, 10-17 ביוני 2027, תיק יד בלבד"},
    {"role": "assistant", "content": "קלטתי. נגישות - יש צורך בהתאמות מיוחדות?"},
], dict(baggage_state))


def _fake_post_claude_quiet(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({"trip_update": {}, "restart_request": False, "restart_evidence": None, "dates_evidence": None, "destination_evidence": None, "baggage_evidence": None})
    if source == "guided_extract":
        return json.dumps({"status": "answered", "needs": [], "confidence": "high", "also_mentioned": {}})
    if source == "tinkerbell_reply":
        return "תשובה לדוגמה."
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_quiet):
    whatsapp_bridge.ariella_turn(m_baggage_quiet, "לא, אין צורך")
_quiet_rows = [
    r for r in ai_usage.diagnostic_rows("baggage_change", include_test=True)
    if r.get("member_id") == m_baggage_quiet
]
check("regression: a turn that never touches flight.baggage writes no baggage_change row",
      not _quiet_rows)

# Regression: a genuinely quoted live baggage correction IS accepted.
m_baggage_correction = _make_member("qa-dryrun5b-sticky-baggage-correction@example.com")
database.save_ariella_conversation(m_baggage_correction, [
    {"role": "user", "content": "פאפוס, זוג, 10-17 ביוני 2027, תיק יד בלבד"},
    {"role": "assistant", "content": "קלטתי - תיק יד בלבד. יש צורך בהתאמות נגישות?"},
], dict(baggage_state))


def _fake_post_claude_correction(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {"flight": {"baggage": ["checked_bag"]}},
            "restart_request": False, "restart_evidence": None, "dates_evidence": None,
            "destination_evidence": None, "baggage_evidence": "רגע, בעצם נצטרך מזוודה",
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "עדכנתי למזוודה בבטן המטוס."
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_correction):
    whatsapp_bridge.ariella_turn(m_baggage_correction, "רגע, בעצם נצטרך מזוודה")
_correction_state = (database.load_ariella_conversation(m_baggage_correction) or {}).get("trip_state") or {}
check("regression: a genuinely quoted live baggage correction IS accepted - flight.baggage actually changes",
      _correction_state.get("flight", {}).get("baggage") == ["checked_bag"])


if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DRYRUN5B-STICKY-BAGGAGE-EVIDENCE TESTS PASSED")
