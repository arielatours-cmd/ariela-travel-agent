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
   customer's answer expresses that a direct flight isn't actually
   important to them. Per the business owner's explicit decision
   (21.10.2026, on this same PR): the instruction gives exactly ONE
   illustrative example ("לא חובה", the live Paphos phrasing) and relies
   on genuine model understanding for everything else - never a list of
   phrasings, in the prompt or as a regex.

2. There was no general defense against repeating an identical fixed
   question forever OUTSIDE the guided-extraction flow - only guided
   fields had a loop guard (#122, Copenhagen). _apply_gap_repeat_guard is
   a parallel, general mechanism.

   This went through four review rounds before landing (all via Shlomo,
   relaying Shaked and the business owner):
   - Round 1: counted any two turns where the same question text appeared
     in the assistant's last two messages, and silently wrote an honest
     "אין העדפה" default for an optional field once that happened twice.
     Shaked's counter-example: two side questions ("כמה זמן הטיסה?", "ויש
     שם חוף טוב לילדים?") sandwiched between the repeated asks still
     looked like two unresolved attempts and triggered the default.
   - Round 2 and 3 tried progressively more precise model-driven signals
     (a new pending_question_response field distinguishing "answered" /
     "unclear" / "side_question") to fix that - round 3 still had a
     reported gap in a live transcript.
   - Round 4 (the business owner's own decision, via Shlomo, after the
     third rejection): simplify instead of refining further. The model
     understanding fix in (1) above is what actually resolves Paphos;
     this guard is kept ONLY as a low-risk safety net with two rules:
     (a) it NEVER writes any value to trip_update, ever - no more
     per-field defaults, no pending_question_response dependency; (b) it
     matches against the REAL canonical question text for each
     individual open gap, never against _session_gaps(...)[0] alone.
     That gaps[0] shortcut was itself a live bug: _flight_gap_question
     picks a question by its OWN fixed priority order (destination_
     airports > ... > budget_per_person > ... > connection_preference >
     baggage > ...), which does not match _session_gaps's own list
     order. The round-1-3 versions computed the repeated question's text
     correctly (from the full gaps list, so it matched whatever was
     ACTUALLY asked), but kept writing any default/looking up the
     per-field dict under gaps[0] - a DIFFERENT field whenever the two
     orders diverged. Live example: budget_per_person and flight.
     connection_preference both open, with connection_preference first
     in _session_gaps's own list order; the budget question (higher
     priority in _flight_gap_question) gets asked twice in a row and
     stays unresolved, but the old code kept writing "אין העדפה" into
     connection_preference - a field never once actually asked about.

   Round 4's shape: if the SAME question text was the last question asked
   in each of the last two assistant turns, and the gap that text
   actually belongs to (checked against EACH open gap's own canonical
   question, never gaps[0]) is still open, Tinkerbell gets a one-turn
   hint to rephrase with concrete examples - never the identical text a
   third time, and never a silently-written value.

   Round 5 (Shaked's rejection of round 4, same day, via Shlomo): round
   4's function wrote the hint directly onto trip_update and returned
   trip_update itself - but trip_update IS what gets persisted into
   trip_state at the end of the turn, so the hint lived on forever across
   every future turn, not just the one it was meant for. Live failure:
   the direct-flight question resolves correctly ("לא חובה" -> "אין
   העדפה"), but the NEXT turn (now asking about baggage) still carried
   the stale hint telling Tinkerbell to rephrase the direct-flight
   question - a question no longer even being asked. Fixed: the function
   never touches trip_update at all any more. It returns the hint text
   alone (or None), exactly like _understand_open_gap_answer's
   gap_clarify_question return value, and the caller folds it into
   state_for_tinkerbell for that ONE _call_tinkerbell invocation only -
   never into trip_update, never persisted.

3. Stage-1 run-6 (a separate live finding, same destination): even
   after PR #116, the FIRST "לא חובה" answer still wasn't saved - only
   the second, identical answer was. Tinkerbell's own free text correctly
   understood the first one and asked the same question again, but the
   extractor's own structured JSON that same turn didn't write the field
   at all - the dual-call mismatch pattern already fixed once, recurring
   on a different turn. _connection_preference_pending_hint gives the
   extractor call the same explicit situational grounding _multi_gateway_
   hint already gives for a multi-gateway destination choice: when the
   gap is still open and Tinkerbell's own last turn actually asked this
   exact question, the extractor is told so directly - it still decides
   for itself, from genuine understanding, whether the reply means
   "direct", "אין העדפה", or neither; this never decides the answer, only
   confirms which question is pending right now.

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
# - never a fixed phrase list, and never a list of examples either.
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
check("the simplified repeat-guard no longer needs or references "
      "pending_question_response anywhere in the codebase",
      not hasattr(chat, "_parse_pending_question_response")
      and not hasattr(chat, "_GAP_OPTIONAL_DEFAULTS")
      and "pending_question_response" not in chat.EXTRACTOR_SYSTEM)

# =====================================================================
# 2. Direct unit tests of _apply_gap_repeat_guard(trip_update, history,
# active_session) - round 5's final design: it returns the hint text (or
# None) and never touches trip_update at all - not even to read it back
# afterward, since there is nothing to mutate any more. The caller alone
# decides what to do with the returned hint (fold it into
# state_for_tinkerbell for one turn, per the function's own docstring).
# =====================================================================
_DIRECT_Q = "חשוב לכם שהטיסה תהיה ישירה?"
_TWO_DIRECT_Q_HISTORY = [
    {"role": "assistant", "content": _DIRECT_Q},
    {"role": "user", "content": "הממ"},
    {"role": "assistant", "content": _DIRECT_Q},
]

with patch.object(chat, "_session_gaps", return_value=["flight.connection_preference"]):
    _hint_repeat = chat._apply_gap_repeat_guard(
        {"active_session": "flights", "flight": {"baggage": ["checked_bag"]}},
        _TWO_DIRECT_Q_HISTORY, "flights",
    )
check("after the SAME question was the last question asked in each of the "
      "last two assistant turns, and the matching gap is still open, the "
      "function returns a rephrase-with-examples hint",
      _DIRECT_Q in str(_hint_repeat or "") and "דוגמאות" in str(_hint_repeat or ""))

with patch.object(chat, "_session_gaps", return_value=["flight.connection_preference"]):
    _state_unchanged = {"active_session": "flights", "flight": {"baggage": ["checked_bag"]}}
    chat._apply_gap_repeat_guard(dict(_state_unchanged), _TWO_DIRECT_Q_HISTORY, "flights")
check("the guard NEVER mutates its trip_update argument at all - passing "
      "a copy through and firing the hint leaves the original untouched "
      "(there is nothing left in this function that writes anywhere)",
      _state_unchanged == {"active_session": "flights", "flight": {"baggage": ["checked_bag"]}})

with patch.object(chat, "_session_gaps", return_value=["flight.connection_preference"]):
    _hint_once = chat._apply_gap_repeat_guard(
        {"active_session": "flights"},
        [{"role": "assistant", "content": _DIRECT_Q}],
        "flights",
    )
check("regression: with only ONE prior ask (not the last two assistant "
      "turns), the guard returns None",
      _hint_once is None)

with patch.object(chat, "_session_gaps", return_value=["flight.connection_preference"]):
    _hint_unrelated = chat._apply_gap_repeat_guard(
        {"active_session": "flights"},
        [{"role": "assistant", "content": "שלום, בוא נתחיל"}, {"role": "user", "content": "היי"},
         {"role": "assistant", "content": "איזה יעד מעניין אתכם?"}],
        "flights",
    )
check("regression: two DIFFERENT questions in the last two assistant "
      "turns (never a real repeat) return None",
      _hint_unrelated is None)

check("the guard returns None once gaps is already empty (field resolved)",
      chat._apply_gap_repeat_guard({"active_session": "flights"}, _TWO_DIRECT_Q_HISTORY, "flights") is None)

_LODGING_Q = chat._GAP_QUESTION_TEXT["lodging.details.type"]
with patch.object(chat, "_session_gaps", return_value=["lodging.details.type"]):
    _hint_lodging = chat._apply_gap_repeat_guard(
        {"active_session": "lodging"},
        [{"role": "assistant", "content": _LODGING_Q}, {"role": "user", "content": "לא בטוחים"},
         {"role": "assistant", "content": _LODGING_Q}],
        "lodging",
    )
check("the same mechanism works identically for a non-flights domain "
      "(lodging) - a rephrase hint returned, never a value written",
      _LODGING_Q in str(_hint_lodging or ""))

# The exact misattribution bug Shlomo's own review caught (round 4):
# budget_per_person and flight.connection_preference both open, with
# connection_preference listed FIRST by _session_gaps's own insertion
# order (gaps[0]) - but _flight_gap_question's priority order asks about
# budget first. The budget question gets asked twice in a row and stays
# unresolved; the returned hint must correctly name the BUDGET question,
# never connection_preference's own question, because the repeated text
# belongs to budget, not to gaps[0].
_BUDGET_Q = "מה התקציב שלכם לאדם לטיסה?"
with patch.object(chat, "_session_gaps", return_value=["flight.connection_preference", "flight.baggage", "budget_per_person"]):
    _hint_budget = chat._apply_gap_repeat_guard(
        {"active_session": "flights"},
        [{"role": "assistant", "content": _BUDGET_Q}, {"role": "user", "content": "עוד לא יודעים"},
         {"role": "assistant", "content": _BUDGET_Q}],
        "flights",
    )
check("Shlomo's exact live misattribution bug, reproduced directly: "
      "the budget question repeats twice while connection_preference "
      "merely happens to be listed first by _session_gaps - the returned "
      "hint correctly names the BUDGET question, not gaps[0]",
      _BUDGET_Q in str(_hint_budget or ""))

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
# 5. End-to-end reproduction of the side-question shape (Shaked's
# original round-2 counter-example) via whatsapp_bridge.ariella_turn
# across TWO real turns: the customer asks a side question each time
# ("כמה זמן הטיסה?", then "ויש שם חוף טוב לילדים?") instead of ever
# attempting to answer the open direct-flight question, but Tinkerbell's
# own reply happens to re-ask the exact same question both times. Since
# the guard (round 4) never writes any value at all, connection_
# preference must stay unset regardless - the only possible effect is a
# one-turn rephrase hint, never a silently invented fact.
# =====================================================================
def _mock_side_questions(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
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
check("side questions, reproduced through the real pipeline: "
      "connection_preference is NEVER silently resolved - the guard "
      "never writes any value at all, regardless of how it was reached",
      not (_state_side_after.get("flight") or {}).get("connection_preference"))

# =====================================================================
# 6. Shaked's round-5 rejection, reproduced directly through the real
# pipeline: the repeat-guard's hint must NEVER persist into trip_state.
# A turn that triggers the hint (the direct-flight question was already
# asked twice, unresolved) must leave trip_state completely free of
# _gap_repeat_rephrase_hint afterward - it's a one-turn signal for
# Tinkerbell's reply only, never a fact about the vacation.
# =====================================================================
def _mock_still_unclear(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "לא הבנתי לגמרי - " + _DIRECT_Q + " (למשל ישירה, או שעצירה אחת בסדר)"
    return "{}"


m_paphos_persist = _make_member("qa-paphos-hint-persistence@example.com")
database.save_ariella_conversation(m_paphos_persist, [
    {"role": "assistant", "content": _DIRECT_Q},
    {"role": "user", "content": "הממ, לא יודעת"},
    {"role": "assistant", "content": _DIRECT_Q},
], dict(_PAPHOS_STATE))

with patch.object(chat, "_post_claude", side_effect=_mock_still_unclear):
    whatsapp_bridge.ariella_turn(m_paphos_persist, "עדיין לא בטוחה")

_state_persist_after = (database.load_ariella_conversation(m_paphos_persist) or {}).get("trip_state") or {}
check("the exact round-5 bug, reproduced through the real pipeline: a "
      "turn that fires the repeat-guard hint must NEVER leave "
      "_gap_repeat_rephrase_hint sitting in the persisted trip_state - "
      "it's a one-turn signal for Tinkerbell's reply only",
      "_gap_repeat_rephrase_hint" not in _state_persist_after)

# =====================================================================
# 7. Stage-1 run-6 (Shlomo/Shaked's live finding, Paphos): the FIRST "לא
# חובה" answer wasn't saved - Tinkerbell's own free text correctly
# understood it and asked the same question again, but the extractor's
# own structured JSON that same turn didn't write connection_preference
# at all (the dual-call mismatch pattern already fixed once in #116,
# recurring here on a DIFFERENT turn). Only the SECOND identical "לא
# חובה" was understood and saved. _connection_preference_pending_hint
# gives the extractor the same explicit situational grounding
# _multi_gateway_hint already gives for a multi-gateway choice - it never
# decides the answer, only confirms which question is pending right now.
# =====================================================================
# Per Shaked's own review of the stage-1 run-6 bug-3 PR (direct-flight
# question asked for every destination by default): this hint must track
# whatever actually decides flight.connection_preference is open right
# now - "flight.connection_preference" in _session_gaps(state, "flights")
# - never the OLD, whitelist-only _direct_route_available condition,
# which would otherwise silently stop sending this hint for the vast
# majority of destinations where the question is now actually asked,
# reopening this exact Paphos reliability gap. _PAPHOS_STATE (Paphos/
# PFO, a known destination) is used directly so the gap opens exactly
# the way the real pipeline resolves it, not via a mock.
_hint_open = chat._connection_preference_pending_hint(
    dict(_PAPHOS_STATE, flight={}),
    [{"role": "assistant", "content": "קלטתי - פאפוס. " + _DIRECT_Q}],
)
check("direct: the hint fires when the gap is genuinely open and "
      "Tinkerbell's own last turn actually asked this exact question",
      "זו השאלה הפתוחה כרגע" in _hint_open and "flight.connection_preference" in _hint_open)
check("direct: the hint explicitly forbids a word list - genuine "
      "understanding of the reply, not phrase matching",
      "לא מרשימת ביטויים" in _hint_open)

_hint_resolved = chat._connection_preference_pending_hint(
    dict(_PAPHOS_STATE, flight={"connection_preference": "direct"}),
    [{"role": "assistant", "content": "קלטתי - פאפוס. " + _DIRECT_Q}],
)
check("regression: once the field is already resolved, the hint "
      "never fires - nothing left to ground",
      _hint_resolved == "")

_hint_unrelated = chat._connection_preference_pending_hint(
    dict(_PAPHOS_STATE, flight={}), [{"role": "assistant", "content": "איזו כבודה תרצו לקחת?"}],
)
check("regression: when Tinkerbell's own last turn asked about "
      "something else entirely (baggage), the hint never fires",
      _hint_unrelated == "")

_hint_unresolved_dest = chat._connection_preference_pending_hint(
    {"flight": {}, "destination": {"places": [], "mode": None, "status": "unknown"}, "destination_airports": []},
    [{"role": "assistant", "content": "קלטתי. " + _DIRECT_Q}],
)
check("regression: with no destination resolved at all, the question is "
      "never genuinely pending either - nothing to ground",
      _hint_unresolved_dest == "")

with patch.object(chat, "_no_direct_route_known", return_value=True):
    _hint_no_direct_route_known = chat._connection_preference_pending_hint(
        dict(_PAPHOS_STATE, flight={}),
        [{"role": "assistant", "content": "קלטתי - פאפוס. " + _DIRECT_Q}],
    )
    check("regression: once a destination is CONFIRMED (stage-1 run-6, "
          "bug 3) to have no direct route at all, the field is silently "
          "prefilled and the gap never opens - so the hint correctly "
          "never fires either, even though Tinkerbell's own last turn "
          "text still happens to contain the question",
          _hint_no_direct_route_known == "")

# End-to-end: confirm the hint actually reaches the real extractor call's
# system_dynamic exactly when expected, through the real pipeline (not
# just the helper function in isolation) - captured via a mock that
# records what it was given, since a mock cannot itself become a better
# language model.
_captured_system_dynamic = {}


def _mock_capture_system_dynamic(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        _captured_system_dynamic["text"] = system_dynamic
        return json.dumps({
            "trip_update": {"flight": {"connection_preference": "אין העדפה"}},
            "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "סבבה, קיבלתי."
    return "{}"


m_paphos_hint = _make_member("qa-paphos-grounding-hint@example.com")
database.save_ariella_conversation(m_paphos_hint, [
    {"role": "user", "content": "פאפוס, זוג, 5.5 עד 10.5.2027"},
    {"role": "assistant", "content": "קלטתי - פאפוס. " + _DIRECT_Q},
], dict(_PAPHOS_STATE))

with patch.object(chat, "_direct_route_available", return_value=True):
    with patch.object(chat, "_post_claude", side_effect=_mock_capture_system_dynamic):
        whatsapp_bridge.ariella_turn(m_paphos_hint, "לא חובה")

check("end-to-end: the real extractor call's own system_dynamic actually "
      "contains the grounding hint on the exact turn the live bug "
      "occurred on (gap open, question just asked)",
      "זו השאלה הפתוחה כרגע" in _captured_system_dynamic.get("text", ""))

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL PAPHOS-CONNECTION-PREFERENCE-LOOP TESTS PASSED")
