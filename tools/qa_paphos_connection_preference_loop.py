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
   a parallel, general mechanism: once the SAME gap-question has been
   genuinely attempted and not understood twice in a row, the next ask
   never repeats the identical text again - an OPTIONAL preference-type
   gap (today, only flight.connection_preference) gets its honest "אין
   העדפה" default written directly, closing it silently; any other
   (required) gap instead gets a one-turn hint telling Tinkerbell to
   rephrase with concrete examples, never the same text a third time.

   REWORKED 21.10.2026 (Shaked rejected the first version, via Shlomo):
   that version counted any two turns where the same question text
   appeared in the assistant's last two messages, with no regard for
   whether the customer ever actually tried to answer it - two side
   questions in a row ("כמה זמן הטיסה?", "ויש שם חוף טוב לילדים?")
   between the repeated asks still counted as two unresolved attempts.
   Reworked to track a persistent per-gap streak driven by
   pending_question_response - the extractor's own genuine understanding
   (never a word list) of whether the customer's current message actually
   attempted to answer the open question ("unclear"), resolved it
   ("answered"), or never addressed it at all ("side_question" - which
   neither advances nor resets the streak).

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
# 1b. pending_question_response - the new signal (21.10.2026, Shlomo/
# Shaked's review of the repeat-guard fix) the extractor returns every
# turn: the model's own genuine understanding of whether the customer's
# current message attempted to answer the single open question
# Tinkerbell's last turn asked, never a word list.
# =====================================================================
check("EXTRACTOR_SYSTEM documents the pending_question_response field "
      "and all three of its real values",
      "pending_question_response" in chat.EXTRACTOR_SYSTEM
      and '"answered"' in chat.EXTRACTOR_SYSTEM
      and '"unclear"' in chat.EXTRACTOR_SYSTEM
      and '"side_question"' in chat.EXTRACTOR_SYSTEM)
check("the instruction explicitly rules out mistaking a side question "
      "for a failed attempt to answer",
      "לעולם איננה ניסיון שנכשל" in chat.EXTRACTOR_SYSTEM)

check("_parse_pending_question_response accepts all three real values",
      chat._parse_pending_question_response('{"pending_question_response":"answered"}') == "answered"
      and chat._parse_pending_question_response('{"pending_question_response":"unclear"}') == "unclear"
      and chat._parse_pending_question_response('{"pending_question_response":"side_question"}') == "side_question")
check("_parse_pending_question_response defaults to None on a missing "
      "field, an unrecognized value, or unparseable JSON - never silently "
      "treated as a resolved or failed answer either way",
      chat._parse_pending_question_response('{}') is None
      and chat._parse_pending_question_response('{"pending_question_response":"maybe"}') is None
      and chat._parse_pending_question_response('not json at all') is None)

# =====================================================================
# 2. Direct unit tests of _apply_gap_repeat_guard - the general, non-
# guided loop guard. REWORKED 21.10.2026 (Shaked rejected the history-
# text-matching version, PR #116 round 2, via Shlomo): it's now driven by
# pending_question_response - the extractor's own genuine understanding
# of whether the customer's CURRENT message was an attempt to answer the
# open gap-question - and a persistent per-gap streak carried across
# turns in trip_update["_gap_unclear_streak"], never raw history
# text-matching. "unclear" (tried to answer, not understood) advances the
# streak; "side_question" (the live Paphos-review counter-example: a
# question about flight duration, or about a kids' beach, that never
# addresses the open question at all) leaves it exactly as it was - it
# must never count as a repeat.
#
# REWORKED AGAIN, same day (Shaked's second rejection, round 3, via
# Shlomo): "answered" does NOT clear the streak either, when this
# function still finds the gap open (which it always does at this point,
# by construction - see the function's own docstring). The live Paphos
# transcript had Tinkerbell's own free text correctly say "הבנתי, אין
# העדפה" turn after turn while connection_preference stayed null the
# whole time - the model's pending_question_response="answered" was
# simply wrong about its own trip_update actually landing. Treating
# "answered" as a reset meant the streak never reached two, and the guard
# never engaged - the exact original infinite loop, unfixed. "answered"
# now counts exactly like "unclear" whenever the gap is still open.
# =====================================================================
_DIRECT_Q = "חשוב לכם שהטיסה תהיה ישירה?"

with patch.object(chat, "_session_gaps", return_value=["flight.connection_preference"]):
    _state_optional = {"active_session": "flights", "flight": {"baggage": ["checked_bag"]}}
    _state_optional = chat._apply_gap_repeat_guard(_state_optional, "unclear", "flights")
    _result_optional = chat._apply_gap_repeat_guard(_state_optional, "unclear", "flights")
check("after the SAME open question was genuinely attempted (and not "
      "understood) twice in a row, the OPTIONAL connection_preference "
      "gap gets its honest 'אין העדפה' default written directly",
      _result_optional.get("flight", {}).get("connection_preference") == "אין העדפה")
check("the default-write never disturbs an unrelated field already in "
      "the same section (baggage stays untouched)",
      _result_optional.get("flight", {}).get("baggage") == ["checked_bag"])

with patch.object(chat, "_session_gaps", return_value=["flight.connection_preference"]):
    _result_too_early = chat._apply_gap_repeat_guard({"active_session": "flights"}, "unclear", "flights")
check("regression: with only ONE unclear attempt so far (not yet twice "
      "in a row), the guard never fires - genuinely needs two unresolved "
      "attempts first",
      "connection_preference" not in _result_too_early.get("flight", {}))

# Shlomo's second review of this exact PR (21.10.2026, same day): the
# live Paphos transcript itself - Tinkerbell's own free text correctly
# understood the answer ("הבנתי, אין העדפה") turn after turn, yet
# connection_preference stayed null the whole time, because the
# extractor's own JSON was internally inconsistent (pending_question_
# response="answered" alongside a trip_update that never actually wrote
# the field). Reproduced directly: two turns marked "answered" with the
# gap STILL open both times (_session_gaps keeps listing it, exactly as
# it would if the write never landed) must NOT be treated as two
# resolutions - the second one must still trigger the honest default,
# or the exact original infinite loop recurs unfixed.
with patch.object(chat, "_session_gaps", return_value=["flight.connection_preference"]):
    _state_answered = {"active_session": "flights"}
    _state_answered = chat._apply_gap_repeat_guard(_state_answered, "answered", "flights")
check("after the FIRST 'answered' turn (gap still open - the write never "
      "landed), the field is not yet written - needs a second unresolved "
      "turn, exactly like 'unclear'",
      "connection_preference" not in _state_answered.get("flight", {}))
with patch.object(chat, "_session_gaps", return_value=["flight.connection_preference"]):
    _result_answered_twice = chat._apply_gap_repeat_guard(_state_answered, "answered", "flights")
check("the exact live Paphos failure, reproduced directly: 'answered' "
      "twice in a row with the gap still open BOTH times (the model's "
      "own claim of understanding didn't actually resolve the field) "
      "must still trigger the honest 'אין העדפה' default on the second "
      "turn - 'answered' is never treated as a free reset while the gap "
      "remains open",
      _result_answered_twice.get("flight", {}).get("connection_preference") == "אין העדפה")

# The exact scenario Shaked's review reported, reproduced directly:
# the SAME open question is asked across three turns, but the customer's
# two replies in between are genuine side questions (flight duration, a
# kids' beach question) that never once attempt to answer it - only
# "unclear" attempts may advance the streak, so two side questions must
# never silently resolve the gap.
with patch.object(chat, "_session_gaps", return_value=["flight.connection_preference"]):
    _state_side = {"active_session": "flights"}
    _state_side = chat._apply_gap_repeat_guard(_state_side, "side_question", "flights")  # "כמה זמן הטיסה?"
    _result_side = chat._apply_gap_repeat_guard(_state_side, "side_question", "flights")  # "ויש שם חוף טוב לילדים?"
check("Shaked's exact counter-example: two side questions in a row "
      "(never an attempt to answer the open question) must NEVER be "
      "mistaken for two unresolved attempts - no default is written",
      "connection_preference" not in _result_side.get("flight", {})
      and "_gap_repeat_rephrase_hint" not in _result_side)

_LODGING_Q = chat._GAP_QUESTION_TEXT["lodging.details.type"]
with patch.object(chat, "_session_gaps", return_value=["lodging.details.type"]):
    _state_lodging = chat._apply_gap_repeat_guard({"active_session": "lodging"}, "unclear", "lodging")
    _result_required = chat._apply_gap_repeat_guard(_state_lodging, "unclear", "lodging")
check("a REQUIRED (non-optional) gap genuinely attempted twice unresolved "
      "never gets a silent default - it gets a rephrase-with-examples "
      "hint instead",
      _LODGING_Q in str(_result_required.get("_gap_repeat_rephrase_hint") or "")
      and "דוגמאות" in str(_result_required.get("_gap_repeat_rephrase_hint") or ""))

with patch.object(chat, "_session_gaps", return_value=["lodging.details.type"]):
    _result_no_repeat = chat._apply_gap_repeat_guard({"active_session": "lodging"}, None, "lodging")
check("regression: pending_question_response=None (no open question to "
      "judge against at all) never triggers either branch",
      "_gap_repeat_rephrase_hint" not in _result_no_repeat
      and "lodging" not in _result_no_repeat)

with patch.object(chat, "_session_gaps", return_value=["flight.connection_preference"]):
    _state_mixed = {"active_session": "flights"}
    _state_mixed = chat._apply_gap_repeat_guard(_state_mixed, "unclear", "flights")
    _state_mixed = chat._apply_gap_repeat_guard(_state_mixed, "side_question", "flights")
    _result_mixed = chat._apply_gap_repeat_guard(_state_mixed, "unclear", "flights")
check("a side question sandwiched between two genuine unclear attempts "
      "doesn't reset the streak (it's simply not counted either way) - "
      "the two real unclear attempts still resolve the optional gap",
      _result_mixed.get("flight", {}).get("connection_preference") == "אין העדפה")

check("the guard is a pure no-op once gaps is already empty (field resolved)",
      chat._apply_gap_repeat_guard({"active_session": "flights"}, "unclear", "flights")
      == {"active_session": "flights"})

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
            "pending_question_response": "answered",
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

# =====================================================================
# 4. Shlomo's review of this exact PR (21.10.2026): _deterministic_
# connection_preference_facts' own word lists must be a true fail-safe
# only - never a parallel path that can override the extractor's genuine
# understanding. Reproduces the concern directly: the field is already
# resolved ("direct") from an earlier turn, the extractor returns no
# update this turn (simulating the model not touching the field, which
# is exactly right once it's already settled), and the customer's
# message/prior question would otherwise make the deterministic
# fallback match "אין העדפה" - the already-resolved field must survive
# untouched, because the fallback must never even run once the gap is
# already closed.
# =====================================================================
_PAPHOS_STATE_RESOLVED = dict(_PAPHOS_STATE, flight={"baggage": ["checked_bag"], "connection_preference": "direct"})


def _mock_model_leaves_it_alone(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "קיבלתי, תודה."
    return "{}"


m_paphos_resolved = _make_member("qa-paphos-resolved-fallback@example.com")
database.save_ariella_conversation(m_paphos_resolved, [
    {"role": "user", "content": "פאפוס, זוג, 5.5 עד 10.5.2027, ישירה"},
    {"role": "assistant", "content": "מעולה, טיסה ישירה. " + _DIRECT_Q},
], dict(_PAPHOS_STATE_RESOLVED))

with patch.object(chat, "_post_claude", side_effect=_mock_model_leaves_it_alone):
    whatsapp_bridge.ariella_turn(m_paphos_resolved, "אין העדפה, מה שיותר נוח")

_state_resolved_after = (database.load_ariella_conversation(m_paphos_resolved) or {}).get("trip_state") or {}
check("the deterministic word-list fallback never overrides an already-"
      "resolved connection_preference, even when the message would "
      "otherwise match its own word list - it's a fail-safe for a still-"
      "open gap only, never a second opinion once the model (or an "
      "earlier turn) already settled the field",
      (_state_resolved_after.get("flight") or {}).get("connection_preference") == "direct")

# =====================================================================
# 5. End-to-end reproduction of Shaked's exact review counter-example
# (21.10.2026) via whatsapp_bridge.ariella_turn across TWO real turns: the
# customer asks a side question each time ("כמה זמן הטיסה?", then "ויש שם
# חוף טוב לילדים?") instead of ever attempting to answer the open direct-
# flight question. With a correctly-behaving extractor (pending_question_
# response="side_question" both times, genuine understanding - never a
# word list performed by this test), the gap must still be open after
# both turns - two side questions must never be mistaken for two
# unresolved answer attempts.
# =====================================================================
def _mock_side_questions(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
            "pending_question_response": "side_question",
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "כשעתיים וחצי טיסה. " + _DIRECT_Q
    return "{}"


m_paphos_side = _make_member("qa-paphos-side-questions@example.com")
database.save_ariella_conversation(m_paphos_side, [
    {"role": "user", "content": "פאפוס, זוג, 5.5 עד 10.5.2027"},
    {"role": "assistant", "content": "קלטתי - פאפוס. " + _DIRECT_Q},
], dict(_PAPHOS_STATE))

with patch.object(chat, "_post_claude", side_effect=_mock_side_questions):
    whatsapp_bridge.ariella_turn(m_paphos_side, "רגע, כמה זמן הטיסה?")
    whatsapp_bridge.ariella_turn(m_paphos_side, "ויש שם חוף טוב לילדים?")

_state_side_after = (database.load_ariella_conversation(m_paphos_side) or {}).get("trip_state") or {}
check("Shaked's exact live counter-example, reproduced through the real "
      "pipeline: two consecutive side questions (never an attempt to "
      "answer the open direct-flight question) must NEVER silently "
      "resolve connection_preference - the gap stays open",
      not (_state_side_after.get("flight") or {}).get("connection_preference"))

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL PAPHOS-CONNECTION-PREFERENCE-LOOP TESTS PASSED")
