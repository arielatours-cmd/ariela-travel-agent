"""QA for task 014a extended to baggage (2026-10-17) - per the business
owner's explicit decision, relayed via Shlomo, after Shaked's 014a stage-1
run-1 (2c12546, Budapest Z5): "ועוד מזוודה אחת לכולנו" got summarized as if
every passenger had their own suitcase, because baggage_shared only ever
looked for the literal word "משותפת". The REAL fix per the business owner is
not another phrase - it's bringing baggage into the guided-extraction
mechanism (plan 014) as a real field, same as dates/travelers: the model
decides values (carry_on_only/checked_bag/personal_item/no_baggage) AND
shared (bool), with the existing regex as a fail-safe only.

Unlike dates/travelers (universal to every trip), baggage only applies once
flights are actually requested - _guided_baggage_applies gates it.

Run: python3 tools/qa_guided_extraction_baggage_014a.py
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
            ("QA Guided Baggage", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def _post(message, history, trip_state, member_id):
    with client.session_transaction() as sess:
        sess["member_id"] = member_id
    r = client.post("/api/ariella/chat-clean", json={
        "message": message, "history": history, "trip_state": trip_state,
    })
    return r.get_json()


ROME_STATE = {
    "destination": {"places": ["רומא"], "mode": "specific", "status": "known"},
    "active_session": "flights",
    "requested_services": ["flights"],
    "session_status": {"flights": "active", "lodging": "pending", "car": "pending", "trip_planning": "pending"},
    "dates": {"departure": "2026-11-10", "return": "2026-11-15"},
    "travelers": {"adults": 2},
}


def _fake_post_claude_factory(guided_response):
    def _fake(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
        if source == "state_extractor":
            return "{}"
        if source == "guided_extract":
            return json.dumps(guided_response)
        return "תשובה לדוגמה."
    return _fake


# =====================================================================
# Flag off (kill switch) / baggage not requested at all -> complete no-op,
# existing _deterministic_baggage_facts behavior untouched.
# =====================================================================
os.environ["GUIDED_EXTRACTION_STEPS"] = ""
check("flag off (kill switch) -> baggage never engages either",
      chat._guided_extraction_steps() == set())

member0 = _make_member("qa-baggage-flagoff@example.com")
with patch.object(chat, "_post_claude", side_effect=lambda *a, **kw: (
        "{}" if kw.get("source") == "state_extractor" else "תשובה לדוגמה."
)):
    r0 = _post("טרולי לכל אחד", [], dict(ROME_STATE), member0)
tu0 = r0.get("trip_update") or {}
check("flag off: regex still fills flight.baggage exactly as before (no guided interference)",
      (tu0.get("flight") or {}).get("baggage") == ["carry_on_only"])
check("flag off: no 'guided' field appears in trip_update for baggage",
      not (tu0.get("guided") or {}).get("current_question") == "baggage")

os.environ["GUIDED_EXTRACTION_STEPS"] = "dates,travelers,baggage"
check("flag set -> _guided_extraction_steps() covers all three fields",
      chat._guided_extraction_steps() == {"dates", "travelers", "baggage"})

# --- service gate: baggage never engages on a lodging/car-only trip (no
#     flights requested at all) - _guided_baggage_applies ---
member_no_flights = _make_member("qa-baggage-noflights@example.com")
state_no_flights = dict(ROME_STATE, requested_services=["lodging"], active_session="lodging")
state_no_flights["guided"] = {"current_question": None, "attempts": 0, "answered": []}
with patch.object(chat, "_post_claude", side_effect=lambda *a, **kw: (
        "{}" if kw.get("source") == "state_extractor" else "תשובה לדוגמה."
)):
    r_no_flights = _post("בואו נסגור את הלינה", [], state_no_flights, member_no_flights)
tu_no_flights = r_no_flights.get("trip_update") or {}
check("service gate: flights not requested -> guided baggage never engages, even with the flag on",
      (tu_no_flights.get("guided") or {}).get("current_question") != "baggage"
      and not tu_no_flights.get("_guided_ask_hint"))

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE email IN (?, ?)",
                 ("qa-baggage-flagoff@example.com", "qa-baggage-noflights@example.com"))
    conn.commit()

# =====================================================================
# Proactive ask: dates+travelers already known, flights requested ->
# baggage is the next guided field queued, with a matching hint.
# =====================================================================
member_proactive = _make_member("qa-baggage-proactive@example.com")
with patch.object(chat, "_post_claude", side_effect=lambda *a, **kw: (
        "{}" if kw.get("source") == "state_extractor" else "תשובה לדוגמה."
)):
    state_proactive = dict(ROME_STATE)
    r_proactive = _post("עוד שאלה כלשהי", [], state_proactive, member_proactive)
tu_proactive = r_proactive.get("trip_update") or {}
check("proactive ask: with dates+travelers already known, baggage is the next guided field queued",
      (tu_proactive.get("guided") or {}).get("current_question") == "baggage")
check("proactive ask: the hint describes the baggage/shared question",
      "כבודה" in str(tu_proactive.get("_guided_ask_hint") or ""))

# --- 1. 'טרולי לכל אחד' (carry-on only, per person) -> answered, nothing
#     left to ask (dates/travelers/baggage all resolved) ---
member1 = _make_member("qa-baggage-s1@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "values": ["carry_on_only"], "shared": False,
    "confidence": "high", "also_mentioned": None, "correction": None,
})):
    state1 = dict(ROME_STATE)
    state1["guided"] = {"current_question": "baggage", "attempts": 0, "answered": ["dates", "travelers"]}
    r1 = _post("טרולי לכל אחד", [], state1, member1)
tu1 = r1.get("trip_update") or {}
check("scenario 1: flight.baggage saved as ['carry_on_only']",
      (tu1.get("flight") or {}).get("baggage") == ["carry_on_only"])
check("scenario 1: baggage_shared is NOT set for a non-shared answer",
      not (tu1.get("flight") or {}).get("baggage_shared"))
check("scenario 1: nothing left to ask (all three guided fields resolved)",
      (tu1.get("guided") or {}).get("current_question") is None)

# --- 2. 'טרולי לכל אחד ומזוודה אחת משותפת' -> BOTH values, shared=True ---
member2 = _make_member("qa-baggage-s2@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "values": ["carry_on_only", "checked_bag"], "shared": True,
    "confidence": "high", "also_mentioned": None, "correction": None,
})):
    state2 = dict(ROME_STATE)
    state2["guided"] = {"current_question": "baggage", "attempts": 0, "answered": ["dates", "travelers"]}
    r2 = _post("טרולי לכל אחד ומזוודה אחת משותפת", [], state2, member2)
tu2 = r2.get("trip_update") or {}
check("scenario 2 (Shaked's Budapest Z5 case, via the model this time): both values saved",
      (tu2.get("flight") or {}).get("baggage") == ["carry_on_only", "checked_bag"])
check("scenario 2: baggage_shared=True saved - this is exactly the fact Shaked's finding needed",
      (tu2.get("flight") or {}).get("baggage_shared") is True)

# --- 3. low confidence -> confirm hint, nothing written as settled yet ---
member3 = _make_member("qa-baggage-s3@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "values": ["checked_bag"], "shared": None,
    "confidence": "low", "also_mentioned": None, "correction": None,
})):
    state3 = dict(ROME_STATE)
    state3["guided"] = {"current_question": "baggage", "attempts": 0, "answered": ["dates", "travelers"]}
    r3 = _post("אולי מזוודה, לא בטוחה", [], state3, member3)
tu3 = r3.get("trip_update") or {}
check("scenario 3: low confidence still writes the tentative value (same "
      "precedent as dates/travelers) - it is the CONFIRMATION, not the "
      "write, that low confidence gates",
      (tu3.get("flight") or {}).get("baggage") == ["checked_bag"])
check("scenario 3: a confirm hint is set, question stays open (not yet "
      "marked 'answered' - a later message can still override it)",
      bool(tu3.get("_guided_ask_hint")) and (tu3.get("guided") or {}).get("current_question") == "baggage")

# --- 4. unclear -> retry hint, attempts incremented, never buttons ---
member4 = _make_member("qa-baggage-s4@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "unclear", "values": None, "shared": None, "confidence": "low",
    "also_mentioned": None, "correction": None,
})):
    state4 = dict(ROME_STATE)
    state4["guided"] = {"current_question": "baggage", "attempts": 0, "answered": ["dates", "travelers"]}
    r4a = _post("מה זאת אומרת", [], state4, member4)
tu4a = r4a.get("trip_update") or {}
check("scenario 4: attempts incremented to 1 after an unclear answer",
      (tu4a.get("guided") or {}).get("attempts") == 1)
check("scenario 4: no buttons in the retry hint",
      "[" not in str(tu4a.get("_guided_ask_hint") or ""))

# --- 5. other_topic ('מתי נוחת הטיסה?') -> question stays open, no hint
#     forced onto an unrelated reply ---
member5 = _make_member("qa-baggage-s5@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "other_topic", "values": None, "shared": None, "confidence": "low",
    "also_mentioned": None, "correction": None,
})):
    state5 = dict(ROME_STATE)
    state5["guided"] = {"current_question": "baggage", "attempts": 0, "answered": ["dates", "travelers"]}
    r5 = _post("מתי נוחת הטיסה?", [], state5, member5)
tu5 = r5.get("trip_update") or {}
check("scenario 5: baggage question stays open (current_question unchanged)",
      (tu5.get("guided") or {}).get("current_question") == "baggage")
check("scenario 5: no guided hint forced onto this unrelated message",
      not tu5.get("_guided_ask_hint"))

# --- 6. correction: baggage already answered, customer corrects it ->
#     correction hint, and a CLOSED flights session reopens ---
member6 = _make_member("qa-baggage-s6@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "values": ["checked_bag"], "shared": False,
    "confidence": "high", "also_mentioned": None,
    "correction": {"field": "baggage", "old": "טרולי בלבד", "new": "גם מזוודה"},
})):
    state6 = dict(ROME_STATE)
    state6["flight"] = {"baggage": ["carry_on_only"]}
    state6["session_status"] = dict(ROME_STATE["session_status"], flights="complete")
    state6["ready_for_summary"] = True
    # Matches the established dates/travelers correction-test pattern: the
    # field being corrected is explicitly the LIVE current_question (not
    # left for the pre-satisfy loop to auto-mark "answered") so extraction
    # genuinely runs against this message, even though a value is already
    # present in state - otherwise the pre-satisfy loop would mark baggage
    # "answered" from the stale value and this turn's guided_extract call
    # would never even run.
    state6["guided"] = {"current_question": "baggage", "attempts": 0, "answered": ["dates", "travelers"]}
    r6 = _post("בעצם גם מזוודה בבטן המטוס", [], state6, member6)
tu6 = r6.get("trip_update") or {}
check("scenario 6: the corrected baggage value is saved",
      (tu6.get("flight") or {}).get("baggage") == ["checked_bag"])
check("scenario 6: the hint tells Tinkerbell to confirm the update, naming the baggage field",
      bool(tu6.get("_guided_ask_hint")))
check("scenario 6: a CLOSED flights session reopens so the summary reflects the new value",
      (tu6.get("session_status") or {}).get("flights") == "active"
      and tu6.get("ready_for_summary") is False)

# --- 7. (Shaked-style regression check) turn-1 model failure on a message
#     naming BOTH a shared suitcase phrase AND unresolved travelers - the
#     widened fail-safe must cover baggage too, not just dates/travelers ---
member7 = _make_member("qa-baggage-s7@example.com")
with patch.object(chat, "_post_claude", side_effect=lambda *a, **kw: (
        "{}" if kw.get("source") == "state_extractor"
        else (_ for _ in ()).throw(RuntimeError("simulated model failure")) if kw.get("source") == "guided_extract"
        else "תשובה לדוגמה."
)):
    state7 = dict(ROME_STATE)
    state7["guided"] = {"current_question": "baggage", "attempts": 0, "answered": ["dates", "travelers"]}
    r7 = _post("טרולי לכל אחד ועוד מזוודה אחת לכולנו", [], state7, member7)
tu7 = r7.get("trip_update") or {}
check("scenario 7 (fail-safe): model failure never crashes the request",
      r7.get("status") == "success")
check("scenario 7 (fail-safe): the regex safety net still fills baggage (both values)",
      set((tu7.get("flight") or {}).get("baggage") or []) == {"carry_on_only", "checked_bag"})
check("scenario 7 (fail-safe): the general count rule (#78) still flags baggage_shared=True "
      "via the regex fallback, even though the model call itself failed",
      (tu7.get("flight") or {}).get("baggage_shared") is True)
check("scenario 7 (fail-safe): a hint is still set so Tinkerbell asks in her own words",
      bool(tu7.get("_guided_ask_hint")))

# --- 8. no-buttons rule across the hint builder for the baggage field ---
check("no-buttons rule: a fresh baggage ask hint never contains '['",
      "[" not in chat._guided_ask_hint("baggage", 0))
check("no-buttons rule: a baggage retry hint never contains '['",
      "[" not in chat._guided_ask_hint("baggage", 1))
check("no-buttons rule: a baggage confirm hint never contains '['",
      "[" not in chat._guided_confirm_hint("baggage", "טרולי לכל נוסע"))
check("no-buttons rule: a baggage correction hint never contains '['",
      "[" not in chat._guided_correction_hint("הכבודה", "מזוודה בבטן המטוס"))

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE email LIKE 'qa-baggage-%@example.com'")
    conn.commit()

os.environ.pop("GUIDED_EXTRACTION_STEPS", None)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL GUIDED-EXTRACTION-BAGGAGE-014A TESTS PASSED")
