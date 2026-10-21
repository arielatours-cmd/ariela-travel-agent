"""QA for Shlomo's relay of the business owner's stage-1 run-4 structural
directive (Tallinn, 9bc5d55) - the FOURTH live failure of the "never invent
dates" bug class, which per her own explicit instruction now gets a
structural fix instead of one more narrow patch:

"אפשר להקדים ביום אחד?" <- Ariella proposed 20.11-30.11, the customer said
"כן", and she wrote "מעדכנת" (updating) - but in practice, state stayed at
21.11-01.12 (the shift was never actually applied). Earlier in the same
conversation, an option DISPLAYED as "21.11-30.11" got SAVED, after "כן",
as 21.11-01.12 - the label shown to the customer and the range actually
committed didn't match (an off-by-one between label and range).

The principle: the model never writes a calendar date at all. The code
renders it from state. Concretely (see ariella_chat_clean.py):
- _dates_truth_hint instructs Tinkerbell to write the literal placeholder
  {{DATES}}/{{DATE_OPTIONS}} instead of any calendar date of her own.
- _render_date_placeholders substitutes it from state's own FINAL dates/
  candidate_ranges this turn - AFTER every extraction/merge/acceptance step
  has already run, wired into _call_tinkerbell right before the existing
  _retry_if_dates_invented structural backstop.
- The exact same candidate_ranges string is what _accept_single_proposed_
  date_range later parses to commit "כן" - one source read twice, not two
  independently-computed strings, so label and saved range can never
  drift apart again.

Four acceptance tests per the business owner's own list:
1. Reproduce the Tallinn shape end-to-end (shift proposed -> shown ->
   confirmed) and prove the label shown and the dates finally saved are
   identical.
2. A free-text shift request when the extractor DOES return shift_days -
   the pending candidate appears and is shown via {{DATE_OPTIONS}}.
3. The same request when the extractor does NOT detect a shift (and the
   narrow regex fallback also does not match the phrasing used) - nothing
   is silently invented or committed; Tinkerbell is left to ask instead.
4. label/range identity holds across MULTIPLE candidate options offered in
   the same turn, not just a single one.

Run: python3 tools/qa_date_placeholder_render.py
"""
import os
import re
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
            ("QA Date Placeholder", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


_BASE_STATE = {
    "destination": {"places": ["טאלין"], "mode": "specific", "status": "known"},
    "destination_airports": ["TLL"],
    "travelers": {"adults": 2},
    "dates": {"departure": "2026-11-21", "return": "2026-12-01", "needs_confirmation": False},
    "requested_services": ["flights"],
    "service_decisions": {"flights": {"wanted": True}},
    "session_status": {"flights": "active", "lodging": "pending", "car": "pending", "trip_planning": "pending"},
    "active_session": "flights",
    "guided": {"current_question": None, "attempts": 0, "answered": ["dates", "travelers", "baggage"]},
}


def _extract_rendered_dd_mm_yyyy_pairs(text):
    """Every (day, month, year) tuple embedded in text, in order of appearance."""
    return [(int(d), int(m), int(y)) for d, m, y in re.findall(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text)]


# =====================================================================
# 1. Reproduce the Tallinn shape end-to-end: "אפשר להקדים ביום אחד?" with
# the model's own structured shift_days + verbatim evidence (the PRIMARY
# path) proposes a candidate; Tinkerbell's reply uses {{DATE_OPTIONS}},
# rendered from that SAME candidate; the customer's "כן" then commits
# EXACTLY the dates that were shown - never a different, drifted pair.
# =====================================================================
_captured_reply_turn1 = {}


def _mock_turn1(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
            "relative_date_hint": {"shift_days": -1}, "relative_date_hint_evidence": "להקדים ביום אחד",
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        reply = f"בטח, {chat._DATE_OPTIONS_PLACEHOLDER} מתאים?"
        _captured_reply_turn1["text"] = reply
        return reply
    return "{}"


m_tallinn = _make_member("qa-tallinn-repro@example.com")
database.save_ariella_conversation(m_tallinn, [
    {"role": "user", "content": "טאלין, זוג, 21.11 עד 1.12.2026"},
    {"role": "assistant", "content": "קלטתי - טאלין, 21.11 עד 1.12. מחפשת טיסות."},
], dict(_BASE_STATE))

with patch.object(chat, "_post_claude", side_effect=_mock_turn1):
    reply1 = whatsapp_bridge.ariella_turn(m_tallinn, "אפשר להקדים ביום אחד?")

_state_after_turn1 = (database.load_ariella_conversation(m_tallinn) or {}).get("trip_state") or {}
_dates_after_turn1 = _state_after_turn1.get("dates") or {}
check("turn 1: the shift proposes a PENDING candidate, never auto-applies "
      "it (departure/return stay at the old, still-confirmed values)",
      _dates_after_turn1.get("needs_confirmation") is True
      and _dates_after_turn1.get("departure") == "2026-11-21"
      and _dates_after_turn1.get("return") == "2026-12-01")
_candidate_turn1 = (_dates_after_turn1.get("candidate_ranges") or [None])[0]
check("turn 1: exactly one candidate_ranges entry exists, shifted by the "
      "model's own structured shift_days (-1 day each)",
      _candidate_turn1 is not None and "20.11.2026" in _candidate_turn1 and "30.11.2026" in _candidate_turn1)
check("turn 1: Tinkerbell's reply used the literal {{DATE_OPTIONS}} "
      "placeholder (never composed her own date text)",
      chat._DATE_OPTIONS_PLACEHOLDER in _captured_reply_turn1.get("text", ""))
check("turn 1: the FINAL reply actually sent to the customer has the "
      "placeholder substituted with exactly the candidate just saved to "
      "state - the same single string, not a second independently-worded "
      "restatement",
      chat._DATE_OPTIONS_PLACEHOLDER not in reply1 and _candidate_turn1 in reply1)

_shown_pairs = _extract_rendered_dd_mm_yyyy_pairs(reply1)
check("turn 1: the reply shown to the customer contains the shifted dates "
      "(20.11.2026, 30.11.2026) - never the old, pre-shift ones",
      (20, 11, 2026) in _shown_pairs and (30, 11, 2026) in _shown_pairs
      and (21, 11, 2026) not in _shown_pairs and (1, 12, 2026) not in _shown_pairs)


def _mock_turn2(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
            "relative_date_hint": None, "relative_date_hint_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return f"מעדכנת - {chat._DATES_PLACEHOLDER}."
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_mock_turn2):
    whatsapp_bridge.ariella_turn(m_tallinn, "כן")

_state_after_turn2 = (database.load_ariella_conversation(m_tallinn) or {}).get("trip_state") or {}
_dates_after_turn2 = _state_after_turn2.get("dates") or {}
check("turn 2 (\"כן\"): the candidate shown in turn 1 is what actually gets "
      "committed - the EXACT Tallinn bug (state silently staying at the "
      "OLD dates despite \"כן\") can no longer happen",
      _dates_after_turn2.get("needs_confirmation") is False
      and _dates_after_turn2.get("departure") == "2026-11-20"
      and _dates_after_turn2.get("return") == "2026-11-30")
check("turn 2: the label shown in turn 1 and the range finally saved are "
      "now provably identical (same (day,month,year) pairs) - the exact "
      "off-by-one class (\"21.11-30.11\" shown, \"21.11-01.12\" saved) is "
      "eliminated by construction",
      (20, 11, 2026) in _shown_pairs and (30, 11, 2026) in _shown_pairs
      and _dates_after_turn2.get("departure") == "2026-11-20"
      and _dates_after_turn2.get("return") == "2026-11-30")

# =====================================================================
# 2. Free-text shift request where the extractor DOES return shift_days -
# already exercised above (turn 1), restated here as its own explicit
# checkpoint per the business owner's acceptance-test list.
# =====================================================================
check("acceptance #2: shift_days detected by the extractor produces a "
      "pending candidate shown via {{DATE_OPTIONS}}, substituted from the "
      "same value saved to state",
      _candidate_turn1 in reply1)

# =====================================================================
# 3. The same kind of request when the extractor does NOT detect a shift
# AND the narrow regex fallback also does not match this exact phrasing
# ("רגע, זה בכלל יכול לזוז?" matches neither _deterministic_shift_days_
# fallback's "לזוז...קדימה/אחורה" pattern nor any direct day count) -
# nothing may be silently invented or committed; the confirmed dates stay
# exactly as they were, and _dates_truth_hint (confirmed-dates branch)
# explicitly tells Tinkerbell to ask rather than write {{DATES}} when no
# actual update exists.
# =====================================================================
check("_deterministic_shift_days_fallback correctly finds nothing for "
      "phrasing outside its narrow pattern (sanity check for test 3's own "
      "premise)",
      chat._deterministic_shift_days_fallback("רגע, זה בכלל יכול לזוז?") is None)


def _mock_no_detection(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
            "relative_date_hint": None, "relative_date_hint_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "לאיזה תאריך בדיוק התכוונת?"
    return "{}"


m_no_shift = _make_member("qa-no-shift-detected@example.com")
database.save_ariella_conversation(m_no_shift, [
    {"role": "user", "content": "טאלין, זוג, 21.11 עד 1.12.2026"},
    {"role": "assistant", "content": "קלטתי - טאלין, 21.11 עד 1.12. מחפשת טיסות."},
], dict(_BASE_STATE))

with patch.object(chat, "_post_claude", side_effect=_mock_no_detection):
    reply_no_shift = whatsapp_bridge.ariella_turn(m_no_shift, "רגע, זה בכלל יכול לזוז?")

_state_no_shift = (database.load_ariella_conversation(m_no_shift) or {}).get("trip_state") or {}
_dates_no_shift = _state_no_shift.get("dates") or {}
check("acceptance #3: with neither the model's structured shift_days nor "
      "the narrow regex fallback detecting a change, the confirmed dates "
      "are left completely untouched - nothing invented, nothing "
      "silently committed",
      _dates_no_shift.get("needs_confirmation") is False
      and _dates_no_shift.get("departure") == "2026-11-21"
      and _dates_no_shift.get("return") == "2026-12-01"
      and not _dates_no_shift.get("candidate_ranges"))
check("acceptance #3: _dates_truth_hint for this exact (still-confirmed, "
      "nothing actually updated) state instructs Tinkerbell to ask rather "
      "than invent a change of her own",
      "שאלי לוודא במקום" in chat._dates_truth_hint(_state_no_shift))

# =====================================================================
# 4. label/range identity across MULTIPLE candidate options in the same
# turn - not just the single-candidate shift shape above.
# =====================================================================
_two_candidates = [
    "יום שבת 21.11.2026–יום שני 30.11.2026",
    "יום שבת 28.11.2026–יום שני 07.12.2026",
]
_multi_state = {"active_session": "flights", "dates": {"needs_confirmation": True, "candidate_ranges": list(_two_candidates)}}


def _mock_multi(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "tinkerbell_reply":
        return f"יש לך שתי אפשרויות: {chat._DATE_OPTIONS_PLACEHOLDER} - מה מתאים?"
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_mock_multi):
    reply_multi = chat._call_tinkerbell("k", "m", [], "מה האפשרויות?", dict(_multi_state))
check("acceptance #4: with TWO candidate options pending, both appear in "
      "the final reply EXACTLY as stored in candidate_ranges - the same "
      "single source read for display as would be read to commit either "
      "one on \"כן\" (via _accept_single_proposed_date_range/"
      "_deterministic_candidate_choice_facts)",
      all(c in reply_multi for c in _two_candidates)
      and chat._DATE_OPTIONS_PLACEHOLDER not in reply_multi)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DATE-PLACEHOLDER-RENDER TESTS PASSED")
