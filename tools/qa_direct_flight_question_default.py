"""QA for the business owner's explicit decision (21.10.2026, stage-1
run-6, relayed by Shlomo): "is a direct flight important to you?" was
only ever asked for a small whitelist of destinations with a KNOWN
direct route (direct_routes: today just LCA/PFO/BKK/HKT) - every other
destination silently skipped the question entirely, even though most of
them have no verified answer either way. "למה בכלל יש שאלה כזו ליעדים
מסוימים? זו שאלה שצריכה להגיע לכל יעד. אלא אם ידוע מראש שאין טיסה ישירה
לזה!"

Full spec, in three parts:

1. Invert the default: ask for EVERY destination, once one is known.
   Skip ONLY when a reliable source confirms in advance that there is no
   direct route at all - never a new manual list embedded in code logic.

2. The skip source itself: a plain data file, data/no_direct_routes.json,
   maintained by Ofek and updated roughly monthly, entirely WITHOUT a
   code change (an edit to the file is the whole update). Starts empty
   in principle, so until Ofek populates it, the question is asked
   everywhere - exactly matching the new default. See
   product/no-direct-routes.md (branch ofek) for her sourcing process;
   the real, currently-live list has 7 destinations (DPS, CGK, KUL, DOH,
   MCT, SIN, CPT).

3. On every flight request, check the destination against this list:
   - Not in the list: ask "חשוב לכם שהטיסה תהיה ישירה?" as always.
   - In the list: never ask - flight.connection_preference is silently
     prefilled with a code-only sentinel ("no_direct_route"), closing the
     gap, and the summary shows "טיסה עם עצירה (אין טיסה ישירה ליעד)".
   - A destination with several possible flight fields (e.g. London's
     airports): it's enough that ONE resolved code is NOT in the list to
     still ask - skipping requires EVERY resolved code to be listed.
   - A value the customer already stated themselves is NEVER overridden -
     not even "direct": if they asked for a direct flight to a
     destination that turns out to have none, Tinkerbell must gently
     surface the conflict and ask how to proceed, never silently replace
     or ignore what they said.

_direct_route_available (the existing "a route IS confirmed" check) is
left untouched and still gates the POSITIVE claim Tinkerbell may make in
conversation ("there's a verified direct route") - it is NOT simply
inverted into _no_direct_route_known. The two checks are deliberately
asymmetric: no row/entry in either source has always meant, and still
means, "unverified either way".

Run: python3 tools/qa_direct_flight_question_default.py
"""
import os
import sys
import sqlite3
import json
import tempfile
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
            ("QA Direct Flight Default", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


# A separate, test-only JSON file - never the real data/no_direct_routes.json
# Ofek maintains - so these tests control their own fixture data without
# perturbing (or depending on) the real, currently-live list.
_TEST_NO_DIRECT_PATH = os.path.join(tempfile.gettempdir(), "qa_no_direct_routes_test.json")
chat._NO_DIRECT_ROUTES_PATH = _TEST_NO_DIRECT_PATH


def _write_no_direct_routes(codes, origin_code="TLV"):
    with open(_TEST_NO_DIRECT_PATH, "w", encoding="utf-8") as fh:
        json.dump({"destinations": [{"origin_code": origin_code, "destination_code": c} for c in codes]}, fh)


def _seed_no_direct_route(destination_code, origin_code="TLV"):
    _write_no_direct_routes([destination_code], origin_code)


def _clear_no_direct_routes():
    _write_no_direct_routes([])


_BASE_STATE = {
    "destination": {"places": ["אוקלנד"], "mode": "specific", "status": "known"},
    "destination_airports": ["AKL"],
    "departure_airport": "TLV",
    "requested_services": ["flights"],
    "service_decisions": {"flights": {"wanted": True}},
    "trip_type": "standard",
    "travelers": {"adults": 2},
    "dates": {"departure": "2027-05-05", "return": "2027-05-10", "needs_confirmation": False},
    "flight": {"baggage": ["checked_bag"]},
    "budget_per_person": {"amount": 1000, "currency": "ILS"},
    "session_status": {"flights": "active", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
    "active_session": "flights",
}

# =====================================================================
# 1. _no_direct_route_known - direct unit tests.
# =====================================================================
_clear_no_direct_routes()
check("regression: a destination with NO row at all is never treated as "
      "'no direct route' - unverified, not negative",
      chat._no_direct_route_known(_BASE_STATE) is False)

_seed_no_direct_route("AKL")
check("a destination with a real entry in the no-direct-route data file "
      "is confirmed as having no direct route",
      chat._no_direct_route_known(_BASE_STATE) is True)

check("an unresolved destination (no places, no destination_airports) "
      "is never 'no direct route' either - nothing to look up",
      chat._no_direct_route_known({"destination": {"places": []}, "destination_airports": []}) is False)

_state_two_codes = dict(_BASE_STATE, destination_airports=["AKL", "WLG"])
_write_no_direct_routes(["AKL"])
check("a destination with several resolved flight codes (e.g. a city with "
      "more than one airport): only ONE of them ('AKL') confirmed is NOT "
      "enough to skip - the other ('WLG') is still unverified, so the "
      "question is still asked",
      chat._no_direct_route_known(_state_two_codes) is False)
_write_no_direct_routes(["AKL", "WLG"])
check("the same two-code destination, with BOTH codes confirmed, is "
      "correctly treated as having no direct route at all",
      chat._no_direct_route_known(_state_two_codes) is True)
_seed_no_direct_route("AKL")

# =====================================================================
# 2. _session_gaps - the inverted default, through the real gap list.
# =====================================================================
_clear_no_direct_routes()
check("regression/default: a destination absent from the no-direct list "
      "(today, basically everywhere) still gets the direct-flight "
      "question - the question is no longer gated on a KNOWN-positive "
      "route the way it used to be",
      "flight.connection_preference" in chat._session_gaps(_BASE_STATE, "flights"))

_seed_no_direct_route("AKL")
check("once the destination is confirmed to have no direct route, the "
      "gap never opens at all - the question is correctly skipped",
      "flight.connection_preference" not in chat._session_gaps(_BASE_STATE, "flights"))

_state_unresolved_dest = dict(_BASE_STATE, destination={"places": [], "mode": None, "status": "unknown"}, destination_airports=[])
check("regression: with no destination resolved yet at all, the gap "
      "never fires prematurely (same as before this change)",
      "flight.connection_preference" not in chat._session_gaps(_state_unresolved_dest, "flights"))

# =====================================================================
# 3. _apply_no_direct_route_default - the silent prefill, and the
# "never override the customer's own value" guarantee.
# =====================================================================
_prefilled = chat._apply_no_direct_route_default(dict(_BASE_STATE, flight={"baggage": ["checked_bag"]}))
check("the gap closes by prefilling the honest fact itself (a code-only "
      "sentinel), never a guess",
      _prefilled["flight"].get("connection_preference") == "no_direct_route")
check("the prefill never disturbs an unrelated field already present",
      _prefilled["flight"].get("baggage") == ["checked_bag"])

_already_direct = chat._apply_no_direct_route_default(
    dict(_BASE_STATE, flight={"baggage": ["checked_bag"], "connection_preference": "direct"})
)
check("a value the customer already stated themselves ('direct') is "
      "NEVER overridden, even when the destination is confirmed to have "
      "no direct route at all",
      _already_direct["flight"].get("connection_preference") == "direct")

_already_no_preference = chat._apply_no_direct_route_default(
    dict(_BASE_STATE, flight={"baggage": ["checked_bag"], "connection_preference": "אין העדפה"})
)
check("a genuinely-answered 'אין העדפה' is also never overridden",
      _already_no_preference["flight"].get("connection_preference") == "אין העדפה")

_clear_no_direct_routes()
_untouched = chat._apply_no_direct_route_default(dict(_BASE_STATE, flight={"baggage": ["checked_bag"]}))
check("regression: with no confirmed no-direct-route fact, the function "
      "is a pure no-op - the field stays exactly as it was",
      "connection_preference" not in _untouched["flight"])
_seed_no_direct_route("AKL")

# =====================================================================
# 4. _flight_connection_line - the new summary wording.
# =====================================================================
check("the summary line for the sentinel reads as an honest fact about "
      "the destination, never a vague 'no preference'",
      chat._flight_connection_line({"connection_preference": "no_direct_route"}) == "טיסה עם עצירה (אין טיסה ישירה ליעד)")
check("regression: 'direct' and 'אין העדפה' still render exactly as "
      "before - the new sentinel check never shadows them",
      chat._flight_connection_line({"connection_preference": "direct"}) == "טיסה ישירה בלבד"
      and chat._flight_connection_line({"connection_preference": "אין העדפה"}) == "ישירה או עם קונקשן")

# =====================================================================
# 5. _direct_route_hint_text - all four branches, highest-priority first.
# =====================================================================
_hint_no_conflict = chat._direct_route_hint_text(dict(_BASE_STATE, flight={"baggage": ["checked_bag"], "connection_preference": "no_direct_route"}))
check("no-direct-route + no customer conflict: Tinkerbell is told to "
      "state the fact naturally and never ask the question",
      "לעולם אל תשאלי אם חשוב לו טיסה ישירה" in _hint_no_conflict)

_hint_conflict = chat._direct_route_hint_text(dict(_BASE_STATE, flight={"baggage": ["checked_bag"], "connection_preference": "direct"}))
check("no-direct-route + the customer explicitly wanted direct: "
      "Tinkerbell is told to surface the real conflict and ask how to "
      "proceed, never ignore it",
      "לשאול איך הוא רוצה להמשיך" in _hint_conflict)

_clear_no_direct_routes()
check("regression: the existing 'no record either way' branch still "
      "applies once there's no confirmed no-direct-route fact",
      "אין רישום של טיסה ישירה מאומתת" in chat._direct_route_hint_text(_BASE_STATE))
_seed_no_direct_route("AKL")

# =====================================================================
# 6. End-to-end through the real pipeline.
# =====================================================================
def _mock_no_update(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
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


# The mock's own tinkerbell_reply is a fixed canned string (it cannot
# itself become a better conversational model) - so the real pipeline
# behavior is verified two ways: the resulting STATE (did the gap close
# or stay open, was the right value prefilled), and the actual hint text
# captured from the real system_dynamic handed to the conversational
# call, exactly like _connection_preference_pending_hint's own end-to-end
# test in qa_paphos_connection_preference_loop.py.
_captured_reply_system_dynamic = {}


def _mock_capture_reply_system_dynamic(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        _captured_reply_system_dynamic["text"] = system_dynamic
        return "קיבלתי, תודה."
    return "{}"


_clear_no_direct_routes()
m_default_ask = _make_member("qa-direct-flight-default-ask@example.com")
database.save_ariella_conversation(m_default_ask, [
    {"role": "assistant", "content": "קלטתי - אוקלנד."},
], dict(_BASE_STATE, flight={"baggage": ["checked_bag"]}))
_captured_reply_system_dynamic.clear()
with patch.object(chat, "_post_claude", side_effect=_mock_capture_reply_system_dynamic):
    whatsapp_bridge.ariella_turn(m_default_ask, "מה שלומך?")
_state_default_ask = (database.load_ariella_conversation(m_default_ask) or {}).get("trip_state") or {}
check("end-to-end regression: a destination not in the no-direct list - "
      "Tinkerbell's own real system_dynamic gets the existing 'no record "
      "either way' hint, never the confirmed-no-direct-route one",
      "אין רישום של טיסה ישירה מאומתת" in _captured_reply_system_dynamic.get("text", ""))
check("end-to-end: connection_preference stays unset (genuinely open) "
      "for a destination not in the no-direct list - the gap is real",
      not (_state_default_ask.get("flight") or {}).get("connection_preference")
      and "flight.connection_preference" in chat._session_gaps(_state_default_ask, "flights"))

_seed_no_direct_route("AKL")
m_no_direct = _make_member("qa-direct-flight-no-direct-route@example.com")
database.save_ariella_conversation(m_no_direct, [
    {"role": "assistant", "content": "קלטתי - אוקלנד."},
], dict(_BASE_STATE, flight={"baggage": ["checked_bag"]}))
_captured_reply_system_dynamic.clear()
with patch.object(chat, "_post_claude", side_effect=_mock_capture_reply_system_dynamic):
    whatsapp_bridge.ariella_turn(m_no_direct, "מה שלומך?")
_state_no_direct = (database.load_ariella_conversation(m_no_direct) or {}).get("trip_state") or {}
check("end-to-end: a confirmed no-direct-route destination - Tinkerbell's "
      "own real system_dynamic gets the 'state it as a fact, never ask' "
      "hint",
      "לעולם אל תשאלי אם חשוב לו טיסה ישירה" in _captured_reply_system_dynamic.get("text", ""))
check("end-to-end: connection_preference is silently prefilled with the "
      "honest fact through the real pipeline, and the gap never opens",
      (_state_no_direct.get("flight") or {}).get("connection_preference") == "no_direct_route"
      and "flight.connection_preference" not in chat._session_gaps(_state_no_direct, "flights"))

m_conflict = _make_member("qa-direct-flight-conflict@example.com")
database.save_ariella_conversation(m_conflict, [
    {"role": "assistant", "content": "קלטתי - אוקלנד."},
], dict(_BASE_STATE, flight={"baggage": ["checked_bag"], "connection_preference": "direct"}))
_captured_reply_system_dynamic.clear()
with patch.object(chat, "_post_claude", side_effect=_mock_capture_reply_system_dynamic):
    whatsapp_bridge.ariella_turn(m_conflict, "מה שלומך?")
_state_conflict = (database.load_ariella_conversation(m_conflict) or {}).get("trip_state") or {}
check("end-to-end: a customer's own already-stated 'direct' survives "
      "untouched even when the destination is confirmed to have no "
      "direct route at all - the conflict is for the conversation to "
      "surface, never for code to silently resolve",
      (_state_conflict.get("flight") or {}).get("connection_preference") == "direct")
check("end-to-end: Tinkerbell's own real system_dynamic gets the "
      "conflict-specific hint (surface it, ask how to proceed) - not the "
      "generic no-conflict phrasing",
      "לשאול איך הוא רוצה להמשיך" in _captured_reply_system_dynamic.get("text", ""))

# =====================================================================
# 7. The REAL production data file (data/no_direct_routes.json) -
# Ofek's confirmed, currently-live list (product/no-direct-routes.md,
# branch ofek, commit c23370c): exactly 7 destinations, Montreal (YUL)
# correctly left OUT after her own correction found a real Air Canada
# direct route to it.
# =====================================================================
_REAL_NO_DIRECT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "no_direct_routes.json")
with open(_REAL_NO_DIRECT_PATH, encoding="utf-8") as fh:
    _real_no_direct = json.load(fh)
_real_codes = {row.get("destination_code") for row in _real_no_direct.get("destinations", []) if row.get("origin_code", "TLV") == "TLV"}
check("the real, live no-direct-route data file has exactly Ofek's 7 "
      "confirmed destinations - no more, no less",
      _real_codes == {"DPS", "CGK", "KUL", "DOH", "MCT", "SIN", "CPT"})
check("regression: Montreal (YUL) is NOT in the list - Ofek's own "
      "correction (a real Air Canada direct route exists) must never be "
      "silently reverted",
      "YUL" not in _real_codes)

# =====================================================================
# 8. _flight_direct_priority (public_site.py) - Shaked's PR review finding:
# the sentinel "no_direct_route" contains "direct" as a literal substring,
# which the deal-priorities substring check (ariella_start_flight_search)
# wrongly matched - every deal for a confirmed no-direct-route destination
# got marked deal_priorities=["direct"], so the UI showed "לא כולל: טיסה
# ישירה" on every single offer and the direct-flight ranking was wrong.
# Extracted into its own small function so this exact logic is directly
# testable without ever running a real search, per her explicit request.
# =====================================================================
import public_site

check("regression: a genuine 'direct' request still gets the priority",
      public_site._flight_direct_priority({"connection_preference": "direct"}) == ["direct"])
check("regression: a model variant phrasing ('nonstop') still matches too",
      public_site._flight_direct_priority({"connection_preference": "nonstop"}) == ["direct"])
check("the no-direct-route sentinel never produces the 'direct' priority, "
      "even though it contains 'direct' as a literal substring - the exact "
      "bug Shaked's PR review caught",
      public_site._flight_direct_priority({"connection_preference": "no_direct_route"}) == [])
check("'אין העדפה' (the customer's own closed 'no preference' answer) also "
      "never produces the 'direct' priority",
      public_site._flight_direct_priority({"connection_preference": "אין העדפה"}) == [])
check("no connection_preference at all (unset/null) never produces the "
      "'direct' priority either",
      public_site._flight_direct_priority({}) == []
      and public_site._flight_direct_priority(None) == [])

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DIRECT-FLIGHT-QUESTION-DEFAULT TESTS PASSED")
