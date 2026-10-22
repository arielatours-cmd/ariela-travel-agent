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
collapsed to the same "one shared suitcase" label. The schema carried
count AND unit ("per_person"/"per_couple"/"total") per item at that point.

Simplified again (20.10.2026), per the business owner's own directive
(relayed by Shlomo) after Shaked's PR #91 review: a group booking is
ALWAYS one uniform baggage choice for every ticket (never a per-passenger
split, short of two separate bookings), so per-passenger unit tracking
(per_person/per_couple/per_child/per_adult/total) was never meaningful in
the first place - every per_couple/unit-differentiated scenario below was
rewritten to the final count-only schema, and a NEW mixed_per_passenger
scenario (2c) covers the customer explicitly asking for a per-passenger
split the booking can't represent. The summary label is still built from
real data (_checked_bag_label), never guessed - just count+size now, no
unit.

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
check("code-level default (config.GUIDED_EXTRACTION_STEPS_DEFAULT) covers dates+travelers+accessibility+baggage+lodging",
      chat._guided_extraction_steps() == {"dates", "travelers", "accessibility", "baggage", "lodging"})

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
    "items": [{"type": "carry_on_only", "count": None}],
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
#     ועוד מזוודה אחת לכולנו" -> two items, checked_bag count=1 ---
member2 = _make_member("qa-baggage-s2@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "no_baggage": False,
    "items": [
        {"type": "carry_on_only", "count": None},
        {"type": "checked_bag", "count": 1},
    ],
    "confidence": "high", "also_mentioned": None, "correction": None,
})):
    state2 = dict(ROME_STATE)
    state2["guided"] = {"current_question": "baggage", "attempts": 0, "answered": ["dates", "travelers"]}
    r2 = _post("טרולי לכל אחד ועוד מזוודה אחת לכולנו", [], state2, member2)
tu2 = r2.get("trip_update") or {}
check("scenario 2 (Shaked's Budapest Z5 case): both items saved",
      (tu2.get("flight") or {}).get("baggage") == ["carry_on_only", "checked_bag"])
check("scenario 2: baggage_detail.checked_bag carries count=1 - the exact fact her finding needed",
      (tu2.get("flight") or {}).get("baggage_detail", {}).get("checked_bag") == {"count": 1})

# --- 2b. Her NEW findings on the same day (count preservation): "שתי
#     מזוודות לכולנו" for 4 travelers -> count=2 must survive, not collapse
#     to "one shared suitcase" ---
member2b = _make_member("qa-baggage-s2b@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "no_baggage": False,
    "items": [{"type": "checked_bag", "count": 2}],
    "confidence": "high", "also_mentioned": None, "correction": None,
})):
    state2b = dict(ROME_STATE)
    state2b["guided"] = {"current_question": "baggage", "attempts": 0, "answered": ["dates", "travelers"]}
    r2b = _post("שתי מזוודות לכולנו", [], state2b, member2b)
tu2b = r2b.get("trip_update") or {}
check("scenario 2b (Shaked's count-preservation finding): count=2 survives, not collapsed to 1",
      (tu2b.get("flight") or {}).get("baggage_detail", {}).get("checked_bag") == {"count": 2})
check("scenario 2b: the built label states '2', never 'מזוודה אחת'",
      "2" in chat._checked_bag_label({"count": 2}))

# --- 2c. mixed_per_passenger - FINAL business-owner decision (22.10.2026,
#     4th and final revision, relayed by Shlomo), fully superseding PR
#     #121's "silently resolve to checked_bag" design after Shaked's
#     rejection (21.10, e2848dc, run-7 bug B): a mixed request is now
#     never resolved and never saved. Ariella explains (her own words)
#     that different baggage per passenger can only be added at the
#     payment stage, then asks one yes/no question - choose the same
#     baggage for everyone? "Yes" moves on to the normal single-group
#     question; "no" keeps the business owner's default, "תיק יד בלבד"
#     (personal_item), never a new/invented value. ---


def _fake_classifier_reply(value):
    """Fakes _mixed_baggage_uniform_choice_by_meaning's yes/no/unclear
    model call (source="classifier") while still letting the main
    extractor's own call (source="state_extractor") through as a no-op."""
    def _fake(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
        if source == "state_extractor":
            return "{}"
        if source == "classifier":
            return value
        return "תשובה לדוגמה."
    return _fake


member2c = _make_member("qa-baggage-s2c@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "no_baggage": False, "mixed_per_passenger": True,
    "items": None, "confidence": "high", "also_mentioned": None, "correction": None,
})):
    state2c = dict(ROME_STATE)
    state2c["guided"] = {"current_question": "baggage", "attempts": 0, "answered": ["dates", "travelers"]}
    r2c = _post("אני עם טרולי בלבד אבל הילדים עם מזוודה", [], state2c, member2c)
tu2c = r2c.get("trip_update") or {}
check("scenario 2c (mixed_per_passenger, first detection): nothing is saved at all",
      not (tu2c.get("flight") or {}).get("baggage"))
check("scenario 2c: baggage field stays open (pending the yes/no reply), never marked answered",
      (tu2c.get("guided") or {}).get("current_question") == "baggage")
check("scenario 2c: the pending flag is set so next turn is read as the yes/no answer",
      (tu2c.get("guided") or {}).get("mixed_baggage_pending") is True)
check("scenario 2c: the hint explains baggage can only differ per passenger at payment time",
      "התשלום" in str(tu2c.get("_guided_ask_hint") or ""))
check("scenario 2c: the hint forbids saving/mentioning any specific baggage choice this turn",
      "אל תשמרי" in str(tu2c.get("_guided_ask_hint") or ""))
check("scenario 2c: the hint asks a yes/no question, never buttons",
      "כן/לא" in str(tu2c.get("_guided_ask_hint") or "") and "כפתורים" in str(tu2c.get("_guided_ask_hint") or ""))

# --- 2c-yes: the customer agrees to one uniform baggage choice - moves on
#     to the normal single-group baggage question, exactly as if the
#     mixed description never happened; still nothing saved yet. ---
member2c_yes = _make_member("qa-baggage-s2c-yes@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_classifier_reply("true")):
    state2c_yes = dict(ROME_STATE)
    state2c_yes["guided"] = {
        "current_question": "baggage", "attempts": 0,
        "answered": ["dates", "travelers"], "mixed_baggage_pending": True,
    }
    r2c_yes = _post("כן, בואו נבחר כבודה אחידה", [], state2c_yes, member2c_yes)
tu2c_yes = r2c_yes.get("trip_update") or {}
check("scenario 2c-yes: pending flag cleared",
      not (tu2c_yes.get("guided") or {}).get("mixed_baggage_pending"))
check("scenario 2c-yes: still nothing saved - the normal baggage question is asked next",
      not (tu2c_yes.get("flight") or {}).get("baggage"))
check("scenario 2c-yes: baggage field stays open, asking the normal 3-option question",
      (tu2c_yes.get("guided") or {}).get("current_question") == "baggage"
      and "תיק יד" in str(tu2c_yes.get("_guided_ask_hint") or ""))

# --- 2c-no: the customer declines - the business owner's default,
#     "תיק יד בלבד" (personal_item - a bare hand bag, the weakest tier),
#     is saved. REVISED per Shaked's rejection (22.10, 6ffbe6d): the first
#     version of this saved carry_on_only (a trolley - a different and
#     bigger thing than "תיק יד בלבד") - never an invented new value
#     either way. ---
member2c_no = _make_member("qa-baggage-s2c-no@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_classifier_reply("false")):
    state2c_no = dict(ROME_STATE)
    state2c_no["guided"] = {
        "current_question": "baggage", "attempts": 0,
        "answered": ["dates", "travelers"], "mixed_baggage_pending": True,
    }
    r2c_no = _post("לא, זה בסדר ככה", [], state2c_no, member2c_no)
tu2c_no = r2c_no.get("trip_update") or {}
check("scenario 2c-no: pending flag cleared",
      not (tu2c_no.get("guided") or {}).get("mixed_baggage_pending"))
check("scenario 2c-no: saves תיק יד בלבד (personal_item), never "
      "carry_on_only or any other invented value",
      (tu2c_no.get("flight") or {}).get("baggage") == ["personal_item"])
check("scenario 2c-no: baggage marked answered and the turn moves on",
      (tu2c_no.get("guided") or {}).get("current_question") != "baggage")

# --- 2c-unclear: the reply doesn't actually answer the yes/no question -
#     ask again, pending flag stays set, nothing saved (same loop-guard
#     pattern as every other guided field). ---
member2c_unclear = _make_member("qa-baggage-s2c-unclear@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_classifier_reply("null")):
    state2c_unclear = dict(ROME_STATE)
    state2c_unclear["guided"] = {
        "current_question": "baggage", "attempts": 0,
        "answered": ["dates", "travelers"], "mixed_baggage_pending": True,
    }
    r2c_unclear = _post("מה זאת אומרת?", [], state2c_unclear, member2c_unclear)
tu2c_unclear = r2c_unclear.get("trip_update") or {}
check("scenario 2c-unclear: pending flag stays set, question asked again",
      (tu2c_unclear.get("guided") or {}).get("mixed_baggage_pending") is True
      and (tu2c_unclear.get("guided") or {}).get("current_question") == "baggage")
check("scenario 2c-unclear: nothing saved",
      not (tu2c_unclear.get("flight") or {}).get("baggage"))

# --- 2d. multiple items in parallel: "טרולי לכל אחד ומזוודה אחת לכל
#     המשפחה" -> carry_on + checked_bag (count=1) - the suitcase must never
#     disappear just because a carry-on was ALSO mentioned in the same
#     message (Shaked's original finding; no per-passenger unit survives
#     for either kind anymore, per the 20.10 directive) ---
member2d = _make_member("qa-baggage-s2d@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "no_baggage": False,
    "items": [
        {"type": "carry_on_only", "count": None},
        {"type": "checked_bag", "count": 1},
    ],
    "confidence": "high", "also_mentioned": None, "correction": None,
})):
    state2d = dict(ROME_STATE)
    state2d["guided"] = {"current_question": "baggage", "attempts": 0, "answered": ["dates", "travelers"]}
    r2d = _post("טרולי לכל אחד ומזוודה אחת לכל המשפחה", [], state2d, member2d)
tu2d = r2d.get("trip_update") or {}
check("scenario 2d (Shaked's 'the suitcase disappeared' finding): both items saved, nothing dropped",
      (tu2d.get("flight") or {}).get("baggage") == ["carry_on_only", "checked_bag"])
check("scenario 2d: the checked bag's count is preserved",
      (tu2d.get("flight") or {}).get("baggage_detail", {}).get("checked_bag") == {"count": 1})

# --- 3. low confidence -> confirm hint, nothing written as settled yet ---
member3 = _make_member("qa-baggage-s3@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "no_baggage": False,
    "items": [{"type": "checked_bag", "count": None}],
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
    "items": [{"type": "checked_bag", "count": None}],
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
#     and must still recover the count via the regex, not just a flag ---
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
check("scenario 7 (fail-safe): count=1 is still recovered for the suitcase "
      "even on a model failure. Per the business owner's 20.10 directive "
      "(a group booking is always one uniform baggage choice for every "
      "ticket), the fail-safe never tracks a per-passenger unit for "
      "either bag kind at all anymore - count is the only detail it ever "
      "recovers. The guided-extraction model call is the real, reliable "
      "mechanism for everything else - this is only the regex fallback "
      "for when that call itself fails.",
      (tu7.get("flight") or {}).get("baggage_detail", {}).get("checked_bag", {}).get("count") == 1
      and "unit" not in (tu7.get("flight") or {}).get("baggage_detail", {}).get("checked_bag", {}))
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
#     function _guided_extract_answer falls back to). traveler_count is
#     kept as a parameter for backward compatibility, but per the business
#     owner's 20.10 directive no per-passenger unit is ever recovered from
#     it anymore - only the stated count ---
check("fail-safe regex: 'שתי מזוודות לכולנו' (4 travelers) keeps count=2, not 'one shared'",
      chat._deterministic_baggage_facts("שתי מזוודות לכולנו", 4)["flight"]["baggage_detail"]["checked_bag"]
      == {"count": 2})
check("fail-safe regex: 'שלוש מזוודות' (5 travelers) keeps count=3",
      chat._deterministic_baggage_facts("שלוש מזוודות", 5)["flight"]["baggage_detail"]["checked_bag"].get("count") == 3)
check("fail-safe regex: 'מזוודה אחת לכל זוג' (4 travelers) keeps count=1, no unit "
      "(per_couple is no longer a tracked concept at all)",
      chat._deterministic_baggage_facts("מזוודה אחת לכל זוג", 4)["flight"]["baggage_detail"]["checked_bag"]
      == {"count": 1})
check("fail-safe regex: 'טרולי לכל אחד ומזוודה אחת לכל המשפחה' (4 travelers) - the "
      "suitcase never disappears (it's prefixed 'ו', no space - 'ומזוודה')",
      chat._deterministic_baggage_facts("טרולי לכל אחד ומזוודה אחת לכל המשפחה", 4)["flight"]["baggage"]
      == ["carry_on_only", "checked_bag"])
check("fail-safe regex: same phrase keeps count=1 even with 'לכל אחד' "
      "elsewhere in the message - no unit guessed since a second baggage "
      "kind (the trolley) is also present, and no unit is tracked at all "
      "anymore even when only one kind is mentioned",
      chat._deterministic_baggage_facts("טרולי לכל אחד ומזוודה אחת לכל המשפחה", 4)["flight"]["baggage_detail"]["checked_bag"]
      == {"count": 1})
check("fail-safe regex: the same phrase with traveler_count=None (not yet known this turn) "
      "still never loses the suitcase - Shaked's exact complaint",
      chat._deterministic_baggage_facts("טרולי לכל אחד ומזוודה אחת לכל המשפחה", None)["flight"]["baggage"]
      == ["carry_on_only", "checked_bag"])

# --- 9. _checked_bag_label builds every label from the data, never guesses
#     a count/size it wasn't given; no unit parameter exists anymore ---
check("label: count=1 -> the plain per-passenger default",
      chat._checked_bag_label({"count": 1}) == "מזוודה אחת לכל נוסע")
check("label: count=3 -> states the real count",
      chat._checked_bag_label({"count": 3}) == "3 מזוודות")
check("label: count=2, size stated -> both facts in the label, size pluralized",
      chat._checked_bag_label({"count": 2, "size": "גדולה"}) == "2 מזוודות גדולות")
check("label: no detail at all -> the classic per-passenger default, with no "
      "invented size (fixed 20.10, Shlomo's priority-5 finding, s12x10 - "
      "a size was never stated so none is claimed)",
      chat._checked_bag_label(None) == "מזוודה אחת לכל נוסע")

# =====================================================================
# Per the business owner's explicit decision (20.10, qa/stage-scenarios.md
# on origin/shaked, section "כבודה - שאלה אחת לכל הקבוצה"): ONE question to
# the whole group naming exactly 3 options, never per-passenger; a short
# "can always add later" note after the answer, then straight to the next
# topic in the same message - never a follow-up question.
# =====================================================================
os.environ["GUIDED_EXTRACTION_STEPS"] = "dates,travelers,baggage"

# --- The question itself names the 3 real options (a deliberate exception
#     to the generic no-enumeration rule - see _guided_ask_hint) and never
#     asks about a difference between passengers. ---
ask_hint = chat._guided_ask_hint("baggage", 0)
check("the baggage question hint names all 3 options so Ariella states them "
      "(תיק יד/טרולי/מזוודה), unlike every other guided field",
      "תיק יד" in ask_hint and "טרולי" in ask_hint and "מזוודה" in ask_hint)
check("the hint explicitly forbids asking about a difference between "
      "passengers",
      "נוסעים" in ask_hint and ("לעולם" in ask_hint or "אין אפשרות" in ask_hint))
check("regression: still no buttons in the baggage ask hint",
      "[" not in ask_hint)

# --- K1 Warsaw (qa/reports/2026-10-20-pr91-live-baggage.md, origin/shaked):
#     Ariella correctly explained uniform baggage but then ASKED a confirm
#     question anyway ("תרצו שנזמין מזוודה בבטן לכולם?"), and separately
#     PROMISED a per-passenger split at booking time ("אנסה לסדר את זה
#     בדיוק ככה"). FINAL decision (22.10.2026): nothing is saved or
#     resolved at all here - she explains the payment-time limitation and
#     asks ONE yes/no question instead (see scenario 2c above for the full
#     yes/no follow-up coverage); still no promise of a per-passenger
#     arrangement at booking time, which this repro's "אנסה לסדר" leak was
#     really about. ---
member_k1 = _make_member("qa-baggage-k1-warsaw@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "no_baggage": False, "mixed_per_passenger": True,
    "items": None, "confidence": "high", "also_mentioned": None, "correction": None,
})):
    state_k1 = dict(ROME_STATE)
    state_k1["guided"] = {"current_question": "baggage", "attempts": 0, "answered": ["dates", "travelers"]}
    r_k1 = _post("ההורים רק עם טרולי, לילדים צריך מזוודה בבטן", [], state_k1, member_k1)
tu_k1 = r_k1.get("trip_update") or {}
check("K1 Warsaw: nothing is saved/resolved - the field stays open pending "
      "the yes/no reply",
      not (tu_k1.get("flight") or {}).get("baggage")
      and (tu_k1.get("guided") or {}).get("current_question") == "baggage"
      and (tu_k1.get("guided") or {}).get("mixed_baggage_pending") is True)
k1_hint = str(tu_k1.get("_guided_ask_hint") or "")
check("K1 Warsaw: no promise of any per-passenger arrangement at booking "
      "time leaks into the hint",
      "אנסה לסדר" not in k1_hint and "בדיוק ככה" not in k1_hint)

# --- K2 Naples (same report): "אני מסתדרת עם תיק קטן, שתי האחרות רוצות
#     מזוודה גדולה" - a SIDE-BY-SIDE description (no "אבל"/contrast word),
#     not the "אני... אבל הם..." shape the original detection instruction
#     was keyed to. Her prompt is now broadened explicitly to cover this
#     phrasing too (see _guided_extract_answer's own mixed_per_passenger
#     instruction) - this mock simulates the model correctly classifying it
#     as mixed per the broadened instruction, and verifies nothing is saved
#     or resolved, and no per-passenger breakdown leaks into the hint. ---
member_k2 = _make_member("qa-baggage-k2-naples@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "no_baggage": False, "mixed_per_passenger": True,
    "items": None, "confidence": "high", "also_mentioned": None, "correction": None,
})):
    state_k2 = dict(ROME_STATE)
    state_k2["guided"] = {"current_question": "baggage", "attempts": 0, "answered": ["dates", "travelers"]}
    r_k2 = _post("אני מסתדרת עם תיק קטן, שתי האחרות רוצות מזוודה גדולה", [], state_k2, member_k2)
tu_k2 = r_k2.get("trip_update") or {}
check("K2 Naples: nothing is saved - no flat value and no per-passenger split",
      not (tu_k2.get("flight") or {}).get("baggage"))
check("K2 Naples: no baggage_detail at all either",
      not (tu_k2.get("flight") or {}).get("baggage_detail"))
check("K2 Naples: no per-passenger attribution anywhere in the hint "
      "(e.g. 'לשתי הנוסעות האחרות')",
      "הנוסעות האחרות" not in str(tu_k2.get("_guided_ask_hint") or "")
      and "לשני הנוסעים" not in str(tu_k2.get("_guided_ask_hint") or ""))

# --- The broadened mixed_per_passenger instruction itself names the
#     side-by-side phrasing explicitly, not just the contrastive one - a
#     regression check on the actual prompt text sent to the model. ---
import inspect
_guided_extract_src = inspect.getsource(chat._guided_extract_answer)
check("the guided_extract baggage prompt's mixed_per_passenger instruction "
      "now explicitly covers a side-by-side description too, not only an "
      "explicit 'but' contrast",
      "צד-לצד" in _guided_extract_src or "מסתדרת עם תיק קטן" in _guided_extract_src)
check("the same instruction tells the model to resolve with confidence "
      "\"high\" (never \"low\") for a mixed request - no discussion needed",
      "ההחלטה ודאית" in _guided_extract_src)

# --- K3/K4 (same report, both already-compliant requests - regression):
#     K3 "טרולי לכל אחד" (a uniform request, NOT mixed) must still resolve
#     to carry_on_only with the "can add a suitcase later" note; K4 "רק
#     תיק יד" resolves to personal_item with the "can add a trolley or
#     suitcase later" note - both in ONE message, immediately followed by
#     the next topic. ---
member_k3 = _make_member("qa-baggage-k3@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "no_baggage": False, "mixed_per_passenger": False,
    "items": [{"type": "carry_on_only", "count": None}],
    "confidence": "high", "also_mentioned": None, "correction": None,
})):
    state_k3 = dict(ROME_STATE)
    state_k3["guided"] = {"current_question": "baggage", "attempts": 0, "answered": ["dates", "travelers"]}
    r_k3 = _post("טרולי לכל אחד", [], state_k3, member_k3)
tu_k3 = r_k3.get("trip_update") or {}
k3_hint = str(tu_k3.get("_guided_ask_hint") or "")
check("K3: a genuinely uniform request ('טרולי לכל אחד') is NOT treated as "
      "mixed - carry_on_only is saved, not checked_bag",
      (tu_k3.get("flight") or {}).get("baggage") == ["carry_on_only"])
check("K3: the follow-up note mentions a suitcase can always be added later",
      "להוסיף מזוודה" in k3_hint)
check("K3: no follow-up question about baggage - the note and the move to "
      "the next topic are the same hint, not a separate turn",
      "?" not in k3_hint.split("עברי")[0] if "עברי" in k3_hint else True)

member_k4 = _make_member("qa-baggage-k4@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "no_baggage": False, "mixed_per_passenger": False,
    "items": [{"type": "personal_item", "count": None}],
    "confidence": "high", "also_mentioned": None, "correction": None,
})):
    state_k4 = dict(ROME_STATE)
    state_k4["guided"] = {"current_question": "baggage", "attempts": 0, "answered": ["dates", "travelers"]}
    r_k4 = _post("רק תיק יד", [], state_k4, member_k4)
tu_k4 = r_k4.get("trip_update") or {}
k4_hint = str(tu_k4.get("_guided_ask_hint") or "")
check("K4: personal-item-only is saved correctly",
      (tu_k4.get("flight") or {}).get("baggage") == ["personal_item"])
check("K4: the follow-up note mentions BOTH a trolley and a suitcase can "
      "always be added later (the weakest tier chosen)",
      "טרולי" in k4_hint and "מזוודה" in k4_hint and "להוסיף" in k4_hint)

# --- Direct unit tests of _baggage_followup_hint - the actual decision
#     table from the business owner's directive. ---
# 22.10 (business owner, replacing a rejected after-the-fact filter): the
# checked bag still gets NO "can add" note for the customer - the hint is
# now an explicit instruction to the model NOT to write one (was None).
check("_baggage_followup_hint: checked_bag chosen -> no note at all - explicit 'add nothing' instruction instead of None",
      "אל תוסיפי שום משפט על הוספת כבודה נוספת" in (chat._baggage_followup_hint(["checked_bag"]) or "")
      and "שאפשר תמיד להוסיף" not in (chat._baggage_followup_hint(["checked_bag"]) or ""))
check("_baggage_followup_hint: carry_on_only chosen -> mentions only a "
      "suitcase can be added",
      chat._baggage_followup_hint(["carry_on_only"]) is not None
      and "מזוודה" in chat._baggage_followup_hint(["carry_on_only"])
      and "טרולי" not in chat._baggage_followup_hint(["carry_on_only"]).split("שאפשר")[1].split("באתר")[0])
check("_baggage_followup_hint: personal_item alone -> mentions BOTH a "
      "trolley and a suitcase can be added",
      chat._baggage_followup_hint(["personal_item"]) is not None
      and "טרולי" in chat._baggage_followup_hint(["personal_item"])
      and "מזוודה" in chat._baggage_followup_hint(["personal_item"]))
check("_baggage_followup_hint: empty/None input never raises and returns "
      "the weakest-tier note (nothing chosen is weaker than a personal item)",
      chat._baggage_followup_hint(None) is not None
      and chat._baggage_followup_hint([]) is not None)

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE email LIKE 'qa-baggage-%@example.com'")
    conn.commit()

os.environ.pop("GUIDED_EXTRACTION_STEPS", None)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL GUIDED-EXTRACTION-BAGGAGE-014A TESTS PASSED")
