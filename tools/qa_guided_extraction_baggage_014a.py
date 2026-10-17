"""QA for task 014a extended to baggage (2026-10-17) - per the business
owner's explicit decision, relayed via Shlomo, after Shaked's 014a stage-1
run-1 (2c12546, Budapest Z5): "ועוד מזוודה אחת לכולנו" got summarized as if
every passenger had their own suitcase, because baggage_shared only ever
looked for the literal word "משותפת". The REAL fix per the business owner is
not another phrase - it's bringing baggage into the guided-extraction
mechanism (plan 014) as a real field, same as dates/travelers: the model
decides, PER ITEM, {type, count, unit}, with the existing regex as a
fail-safe only.

Reworked again the same day, after Shaked's review of the first version
(#78, now closed/superseded): a bare shared/not-shared boolean still lost
real information - "שתי מזוודות לכולנו" and "מזוודה אחת לכל זוג" both
collapsed to the same "one shared suitcase" label. The schema now carries
count and unit ("per_person"/"per_couple"/"total") per item, and the
summary label is built from that data (_checked_bag_label), never guessed.

config.GUIDED_EXTRACTION_STEPS_DEFAULT now includes "baggage" (Shlomo,
2026-10-17): Shaked approves every 014 field before its PR merges anyway,
so there is no extra safety in gating it behind a separate Render env var
first - this lets her test it live on the site immediately.

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
    "travelers": {"adults": 4},
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
# Default ON (Shlomo's request): with no env var at all, baggage is
# covered via config.GUIDED_EXTRACTION_STEPS_DEFAULT, alongside dates/
# travelers - Shaked approves before merge regardless, so no separate
# Render env var gate is needed first.
# =====================================================================
os.environ.pop("GUIDED_EXTRACTION_STEPS", None)
import config as _config
check("code-level default (config.GUIDED_EXTRACTION_STEPS_DEFAULT) covers dates+travelers+baggage+lodging",
      chat._guided_extraction_steps() == {"dates", "travelers", "baggage", "lodging"})

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
    "status": "answered", "no_baggage": False,
    "items": [{"type": "carry_on_only", "count": None, "unit": None}],
    "confidence": "high", "also_mentioned": None, "correction": None,
})):
    state1 = dict(ROME_STATE)
    state1["guided"] = {"current_question": "baggage", "attempts": 0, "answered": ["dates", "travelers"]}
    r1 = _post("טרולי לכל אחד", [], state1, member1)
tu1 = r1.get("trip_update") or {}
check("scenario 1: flight.baggage saved as ['carry_on_only']",
      (tu1.get("flight") or {}).get("baggage") == ["carry_on_only"])
check("scenario 1: no baggage_detail written for a plain carry-on-only answer",
      not (tu1.get("flight") or {}).get("baggage_detail"))
check("scenario 1: nothing left to ask (all three guided fields resolved)",
      (tu1.get("guided") or {}).get("current_question") is None)

# --- 2. Shaked's exact Budapest Z5 repro, via the model: "טרולי לכל אחד
#     ועוד מזוודה אחת לכולנו" -> two items, checked_bag count=1 unit=total ---
member2 = _make_member("qa-baggage-s2@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "no_baggage": False,
    "items": [
        {"type": "carry_on_only", "count": None, "unit": None},
        {"type": "checked_bag", "count": 1, "unit": "total"},
    ],
    "confidence": "high", "also_mentioned": None, "correction": None,
})):
    state2 = dict(ROME_STATE)
    state2["guided"] = {"current_question": "baggage", "attempts": 0, "answered": ["dates", "travelers"]}
    r2 = _post("טרולי לכל אחד ועוד מזוודה אחת לכולנו", [], state2, member2)
tu2 = r2.get("trip_update") or {}
check("scenario 2 (Shaked's Budapest Z5 case): both items saved",
      (tu2.get("flight") or {}).get("baggage") == ["carry_on_only", "checked_bag"])
check("scenario 2: baggage_detail.checked_bag carries count=1, unit=total - the exact fact her finding needed",
      (tu2.get("flight") or {}).get("baggage_detail", {}).get("checked_bag") == {"count": 1, "unit": "total"})

# --- 2b. Her NEW findings on the same day (count preservation): "שתי
#     מזוודות לכולנו" for 4 travelers -> count=2 must survive, not collapse
#     to "one shared suitcase" ---
member2b = _make_member("qa-baggage-s2b@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "no_baggage": False,
    "items": [{"type": "checked_bag", "count": 2, "unit": "total"}],
    "confidence": "high", "also_mentioned": None, "correction": None,
})):
    state2b = dict(ROME_STATE)
    state2b["guided"] = {"current_question": "baggage", "attempts": 0, "answered": ["dates", "travelers"]}
    r2b = _post("שתי מזוודות לכולנו", [], state2b, member2b)
tu2b = r2b.get("trip_update") or {}
check("scenario 2b (Shaked's count-preservation finding): count=2 survives, not collapsed to 1",
      (tu2b.get("flight") or {}).get("baggage_detail", {}).get("checked_bag") == {"count": 2, "unit": "total"})
check("scenario 2b: the built label states '2', never 'מזוודה אחת'",
      "2" in chat._checked_bag_label({"count": 2, "unit": "total"}))

# --- 2c. "מזוודה אחת לכל זוג" for 4 travelers -> per_couple, not total ---
member2c = _make_member("qa-baggage-s2c@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "no_baggage": False,
    "items": [{"type": "checked_bag", "count": 1, "unit": "per_couple"}],
    "confidence": "high", "also_mentioned": None, "correction": None,
})):
    state2c = dict(ROME_STATE)
    state2c["guided"] = {"current_question": "baggage", "attempts": 0, "answered": ["dates", "travelers"]}
    r2c = _post("מזוודה אחת לכל זוג", [], state2c, member2c)
tu2c = r2c.get("trip_update") or {}
check("scenario 2c (Shaked's per_couple finding): unit=per_couple saved, not collapsed to total",
      (tu2c.get("flight") or {}).get("baggage_detail", {}).get("checked_bag") == {"count": 1, "unit": "per_couple"})
check("scenario 2c: the label says 'לכל זוג', never 'משותפת'",
      "לכל זוג" in chat._checked_bag_label({"count": 1, "unit": "per_couple"}))

# --- 2d. multiple items in parallel with different units: "טרולי לכל אחד
#     ומזוודה אחת לכל המשפחה" -> carry_on (implicit per-person) + checked_bag
#     (count=1, unit=total) - the suitcase must never disappear ---
member2d = _make_member("qa-baggage-s2d@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "no_baggage": False,
    "items": [
        {"type": "carry_on_only", "count": None, "unit": "per_person"},
        {"type": "checked_bag", "count": 1, "unit": "total"},
    ],
    "confidence": "high", "also_mentioned": None, "correction": None,
})):
    state2d = dict(ROME_STATE)
    state2d["guided"] = {"current_question": "baggage", "attempts": 0, "answered": ["dates", "travelers"]}
    r2d = _post("טרולי לכל אחד ומזוודה אחת לכל המשפחה", [], state2d, member2d)
tu2d = r2d.get("trip_update") or {}
check("scenario 2d (Shaked's 'the suitcase disappeared' finding): both items saved, nothing dropped",
      (tu2d.get("flight") or {}).get("baggage") == ["carry_on_only", "checked_bag"])
check("scenario 2d: the checked bag's total-for-the-family unit is preserved",
      (tu2d.get("flight") or {}).get("baggage_detail", {}).get("checked_bag") == {"count": 1, "unit": "total"})

# --- 3. low confidence -> confirm hint, nothing written as settled yet ---
member3 = _make_member("qa-baggage-s3@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "no_baggage": False,
    "items": [{"type": "checked_bag", "count": None, "unit": None}],
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
    "status": "unclear", "no_baggage": False, "items": None, "confidence": "low",
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
    "status": "other_topic", "no_baggage": False, "items": None, "confidence": "low",
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
    "status": "answered", "no_baggage": False,
    "items": [{"type": "checked_bag", "count": None, "unit": None}],
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
#     widened fail-safe must cover baggage too, not just dates/travelers,
#     and must still recover count+unit via the regex, not just a flag ---
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
check("scenario 7 (fail-safe): the regex recovers unit=total (not just a bare flag) via the 'לכולנו' word",
      (tu7.get("flight") or {}).get("baggage_detail", {}).get("checked_bag", {}).get("unit") == "total")
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

# --- 7b. Shaked's exact fail-safe regex findings, same day, against #78
#     (now the fail-safe inside this branch): each of her 4 reported
#     phrases, checked directly against _deterministic_baggage_facts (the
#     function _guided_extract_answer falls back to) ---
check("fail-safe regex: 'שתי מזוודות לכולנו' (4 travelers) keeps count=2, not 'one shared'",
      chat._deterministic_baggage_facts("שתי מזוודות לכולנו", 4)["flight"]["baggage_detail"]["checked_bag"]
      == {"unit": "total", "count": 2})
check("fail-safe regex: 'שלוש מזוודות' (5 travelers, no unit word) keeps count=3",
      chat._deterministic_baggage_facts("שלוש מזוודות", 5)["flight"]["baggage_detail"]["checked_bag"].get("count") == 3)
check("fail-safe regex: 'מזוודה אחת לכל זוג' (4 travelers) is per_couple, not total",
      chat._deterministic_baggage_facts("מזוודה אחת לכל זוג", 4)["flight"]["baggage_detail"]["checked_bag"]
      == {"unit": "per_couple", "count": 1})
check("fail-safe regex: 'טרולי לכל אחד ומזוודה אחת לכל המשפחה' (4 travelers) - the "
      "suitcase never disappears (it's prefixed 'ו', no space - 'ומזוודה')",
      chat._deterministic_baggage_facts("טרולי לכל אחד ומזוודה אחת לכל המשפחה", 4)["flight"]["baggage"]
      == ["carry_on_only", "checked_bag"])
check("fail-safe regex: same phrase keeps count=1 and unit=total even with 'לכל אחד' elsewhere in the message",
      chat._deterministic_baggage_facts("טרולי לכל אחד ומזוודה אחת לכל המשפחה", 4)["flight"]["baggage_detail"]["checked_bag"]
      == {"unit": "total", "count": 1})
check("fail-safe regex: the same phrase with traveler_count=None (not yet known this turn) "
      "still never loses the suitcase - Shaked's exact complaint",
      chat._deterministic_baggage_facts("טרולי לכל אחד ומזוודה אחת לכל המשפחה", None)["flight"]["baggage"]
      == ["carry_on_only", "checked_bag"])

# --- 9. _checked_bag_label builds every label from the data, never guesses
#     a count/unit it wasn't given ---
check("label: unit=total, count=1 -> 'מזוודה אחת משותפת לכל הנוסעים'",
      chat._checked_bag_label({"count": 1, "unit": "total"}) == "מזוודה אחת משותפת לכל הנוסעים")
check("label: unit=total, count=3 -> states the real count",
      chat._checked_bag_label({"count": 3, "unit": "total"}) == "3 מזוודות משותפות לכל הנוסעים")
check("label: unit=per_couple, count=1 -> 'מזוודה אחת לכל זוג'",
      chat._checked_bag_label({"count": 1, "unit": "per_couple"}) == "מזוודה אחת לכל זוג")
check("label: unit=per_couple, count=2 -> states the real count",
      chat._checked_bag_label({"count": 2, "unit": "per_couple"}) == "2 מזוודות לכל זוג")
check("label: no unit, count=3 (genuinely ambiguous split) -> states the count, never guesses a unit",
      chat._checked_bag_label({"count": 3, "unit": None}) == "3 מזוודות")
check("label: no detail at all -> the classic per-passenger default, unchanged",
      chat._checked_bag_label(None) == "מזוודה גדולה לכל נוסע")

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE email LIKE 'qa-baggage-%@example.com'")
    conn.commit()

os.environ.pop("GUIDED_EXTRACTION_STEPS", None)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL GUIDED-EXTRACTION-BAGGAGE-014A TESTS PASSED")
