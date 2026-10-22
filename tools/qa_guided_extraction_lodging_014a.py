"""QA for task 014a extended to lodging (plan 014, PR2 per Shlomo's
sequencing 2026-10-17 - the blocker for stage-3 QA) - rebuilt 2026-10-17
alongside #75/#76's rework, after the business owner's two final
decisions (relayed via Shlomo/Ofek the same day):

1. The code never sends a fixed sentence as the reply. It only tracks
   guided.current_question and sets a short hint in trip_update["
   _guided_ask_hint"]; Tinkerbell composes the actual question/retry/
   confirmation herself in her own main reply call (mocked here as
   "תשובה לדוגמה." throughout - this suite tests the STATE/HINT contract).
2. No quick-reply buttons anywhere, ever.
3. GUIDED_EXTRACTION_STEPS now defaults ON for dates/travelers/baggage/
   lodging via config.GUIDED_EXTRACTION_STEPS_DEFAULT (lodging added live
   in this same PR, per Shlomo 2026-10-17 - Shaked approves every 014
   field before its PR merges regardless, so a separate Render env var
   gate first adds no safety). Most scenarios below still set the env var
   explicitly anyway, to stay independent of that default's exact value.

Same guided mechanism already built for dates/travelers, now covering
lodging's own required facts (type, rooms, bathrooms when relevant,
locations, budget/level) - one flag value ("lodging") driving all five in
a fixed order, the code always knowing which one it asked.

Run: python3 tools/qa_guided_extraction_lodging_014a.py
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
            ("QA Guided Lodging", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def _post(message, history, trip_state, member_id):
    with client.session_transaction() as sess:
        sess["member_id"] = member_id
    r = client.post("/api/ariella/chat-clean", json={
        "message": message, "history": history, "trip_state": trip_state,
    })
    return r.get_json()


LODGING_STATE_BASE = {
    "destination": {"places": ["רומא"], "mode": "specific", "status": "known"},
    "active_session": "lodging",
    "requested_services": ["flights", "lodging"],
    "session_status": {"flights": "complete", "lodging": "active", "car": "pending", "trip_planning": "pending"},
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
# Zero-regression: lodging is not in the code-level default yet, so the
# flag must be requested explicitly; "lodging" not requested even with
# the flag on is a complete no-op too.
# =====================================================================
os.environ["GUIDED_EXTRACTION_STEPS"] = ""
check("flag off (kill switch) -> lodging never engages either",
      chat._guided_extraction_steps() == set())

member0 = _make_member("qa-014a-lodging-flagoff@example.com")
type_question_history = [{"role": "assistant", "content": "איזה סוג לינה מתאים לכם?"}]
with patch.object(chat, "_post_claude", side_effect=lambda *a, **kw: (
        "{}" if kw.get("source") == "state_extractor" else "תשובה לדוגמה."
)):
    r0 = _post("דירה", type_question_history, dict(LODGING_STATE_BASE), member0)
tu0 = r0.get("trip_update") or {}
check("flag off: regex still fills lodging.details.type exactly as before",
      (tu0.get("lodging") or {}).get("details", {}).get("type") == "דירה")

os.environ["GUIDED_EXTRACTION_STEPS"] = "lodging"
check("flag set -> _guided_extraction_steps() covers lodging",
      chat._guided_extraction_steps() == {"lodging"})
os.environ.pop("GUIDED_EXTRACTION_STEPS", None)
check("code-level default (config.GUIDED_EXTRACTION_STEPS_DEFAULT) now covers lodging too",
      chat._guided_extraction_steps() == {"dates", "travelers", "accessibility", "baggage", "lodging"})
os.environ["GUIDED_EXTRACTION_STEPS"] = "lodging"

member_no_lodging = _make_member("qa-014a-lodging-notrequested@example.com")
state_no_lodging = dict(LODGING_STATE_BASE, requested_services=["flights"], active_session="flights")
state_no_lodging["guided"] = {"current_question": None, "attempts": 0, "answered": []}
with patch.object(chat, "_post_claude", side_effect=lambda *a, **kw: (
        "{}" if kw.get("source") == "state_extractor" else "תשובה לדוגמה."
)):
    r_no_lodging = _post("מתי הטיסה שלנו?", [], state_no_lodging, member_no_lodging)
tu_no_lodging = r_no_lodging.get("trip_update") or {}
check("service gate: lodging not requested -> guided lodging never engages, even with the flag on",
      (tu_no_lodging.get("guided") or {}).get("current_question") != "lodging_type"
      and not tu_no_lodging.get("_guided_ask_hint"))

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE email IN (?, ?)",
                 ("qa-014a-lodging-flagoff@example.com", "qa-014a-lodging-notrequested@example.com"))
    conn.commit()

# =====================================================================
# Proactive ask: lodging requested, nothing known yet -> the guided
# dispatcher queues lodging_type first and sets a hint, unprompted.
# =====================================================================
member_proactive = _make_member("qa-014a-lodging-proactive@example.com")
with patch.object(chat, "_post_claude", side_effect=lambda *a, **kw: (
        "{}" if kw.get("source") == "state_extractor" else "תשובה לדוגמה."
)):
    state_proactive = dict(LODGING_STATE_BASE)
    r_proactive = _post("בואו נסגור את הלינה", [], state_proactive, member_proactive)
tu_proactive = r_proactive.get("trip_update") or {}
check("proactive ask: lodging_type is the first guided lodging field queued, with a matching hint",
      (tu_proactive.get("guided") or {}).get("current_question") == "lodging_type"
      and "סוג לינה" in str(tu_proactive.get("_guided_ask_hint") or ""))

# --- 1. type answered (hotel) -> moves straight to rooms ---
member1 = _make_member("qa-014a-lodging-s1@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "value": "מלון", "confidence": "high", "also_mentioned": None, "correction": None,
})):
    state1 = dict(LODGING_STATE_BASE)
    state1["guided"] = {"current_question": "lodging_type", "attempts": 0, "answered": []}
    r1 = _post("מלון", [], state1, member1)
tu1 = r1.get("trip_update") or {}
check("scenario 1: type saved as מלון",
      (tu1.get("lodging") or {}).get("details", {}).get("type") == "מלון")
check("scenario 1: next question is rooms",
      (tu1.get("guided") or {}).get("current_question") == "lodging_rooms"
      and "חדרים" in str(tu1.get("_guided_ask_hint") or ""))

# Bathrooms only gets pre-marked "answered" on the NEXT dispatcher call,
# once type is already persisted in state (the pre-satisfied scan runs at
# the top of each turn, before this turn's own answer is merged in).
with patch.object(chat, "_post_claude", side_effect=lambda *a, **kw: (
        "{}" if kw.get("source") == "state_extractor" else "תשובה לדוגמה."
)):
    state1b = dict(LODGING_STATE_BASE)
    state1b["lodging"] = tu1.get("lodging")
    state1b["guided"] = tu1.get("guided")
    r1b = _post("בעצם, בואו נדבר על זה אחר כך", [], state1b, member1)
tu1b = r1b.get("trip_update") or {}
check("scenario 1b: once type=מלון is persisted, bathrooms is pre-marked answered and skipped entirely",
      "lodging_bathrooms" in ((tu1b.get("guided") or {}).get("answered") or [])
      and (tu1b.get("guided") or {}).get("current_question") != "lodging_bathrooms")

# --- 2. type = apartment -> bathrooms question stays live later ---
member2 = _make_member("qa-014a-lodging-s2@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "value": "דירה", "confidence": "high", "also_mentioned": None, "correction": None,
})):
    state2 = dict(LODGING_STATE_BASE)
    state2["guided"] = {"current_question": "lodging_type", "attempts": 0, "answered": []}
    r2 = _post("דירה", [], state2, member2)
tu2 = r2.get("trip_update") or {}
check("scenario 2: apartment type does NOT pre-skip the bathrooms question",
      "lodging_bathrooms" not in ((tu2.get("guided") or {}).get("answered") or []))

# --- 3. rooms: spelled-out number ---
member3 = _make_member("qa-014a-lodging-s3@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "value": 2, "confidence": "high", "also_mentioned": None, "correction": None,
})):
    state3 = dict(LODGING_STATE_BASE)
    state3["lodging"] = {"details": {"type": "דירה"}}
    state3["guided"] = {"current_question": "lodging_rooms", "attempts": 0, "answered": ["lodging_type"]}
    r3 = _post("שני חדרים", [], state3, member3)
tu3 = r3.get("trip_update") or {}
check("scenario 3: rooms=2 saved, moves on to bathrooms (apartment)",
      (tu3.get("lodging") or {}).get("details", {}).get("rooms") == 2
      and (tu3.get("guided") or {}).get("current_question") == "lodging_bathrooms")

# --- 4. bathrooms answered ---
member4 = _make_member("qa-014a-lodging-s4@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "value": 2, "confidence": "high", "also_mentioned": None, "correction": None,
})):
    state4 = dict(LODGING_STATE_BASE)
    state4["lodging"] = {"details": {"type": "דירה", "rooms": 2}}
    state4["guided"] = {"current_question": "lodging_bathrooms", "attempts": 0, "answered": ["lodging_type", "lodging_rooms"]}
    r4 = _post("שני חדרי רחצה", [], state4, member4)
tu4 = r4.get("trip_update") or {}
check("scenario 4: bathrooms=2 saved, moves on to locations",
      (tu4.get("lodging") or {}).get("details", {}).get("bathrooms") == 2
      and (tu4.get("guided") or {}).get("current_question") == "lodging_locations")

# --- 5. locations: "no preference" -> saved without crashing, moves on ---
member5 = _make_member("qa-014a-lodging-s5@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "value": "אין העדפה", "confidence": "high", "also_mentioned": None, "correction": None,
})):
    state5 = dict(LODGING_STATE_BASE)
    state5["lodging"] = {"details": {"type": "דירה", "rooms": 2, "bathrooms": 2}}
    state5["guided"] = {"current_question": "lodging_locations", "attempts": 0, "answered": ["lodging_type", "lodging_rooms", "lodging_bathrooms"]}
    r5 = _post("לא משנה לי", [], state5, member5)
tu5 = r5.get("trip_update") or {}
check("scenario 5: locations='אין העדפה' saved, moves on to budget/level",
      (tu5.get("lodging") or {}).get("details", {}).get("locations") == "אין העדפה"
      and (tu5.get("guided") or {}).get("current_question") == "lodging_budget_or_level")

# --- 6. budget_or_level: a numeric nightly budget ---
member6 = _make_member("qa-014a-lodging-s6@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "budget": 150, "level": None, "confidence": "high", "also_mentioned": None, "correction": None,
})):
    state6 = dict(LODGING_STATE_BASE)
    state6["lodging"] = {"details": {"type": "דירה", "rooms": 2, "bathrooms": 2, "locations": "אין העדפה"}}
    state6["guided"] = {"current_question": "lodging_budget_or_level", "attempts": 0,
                         "answered": ["lodging_type", "lodging_rooms", "lodging_bathrooms", "lodging_locations"]}
    r6 = _post("150 יורו ללילה", [], state6, member6)
tu6 = r6.get("trip_update") or {}
check("scenario 6: budget=150 saved, nothing left to ask (lodging fully resolved)",
      (tu6.get("lodging") or {}).get("details", {}).get("budget") == 150
      and (tu6.get("guided") or {}).get("current_question") is None
      and not tu6.get("_guided_ask_hint"))

# --- 7. budget_or_level: a star rating is a LEVEL, never misread as a
#     tiny nightly budget (Shlomo's 2026-10-15 live bug) ---
member7 = _make_member("qa-014a-lodging-s7@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "budget": None, "level": "יוקרתי", "confidence": "high", "also_mentioned": None, "correction": None,
})):
    state7 = dict(LODGING_STATE_BASE)
    state7["lodging"] = {"details": {"type": "מלון", "rooms": 1}}
    state7["guided"] = {"current_question": "lodging_budget_or_level", "attempts": 0,
                         "answered": ["lodging_type", "lodging_rooms", "lodging_bathrooms", "lodging_locations"]}
    r7 = _post("4 כוכבים ומעלה", [], state7, member7)
tu7 = r7.get("trip_update") or {}
check("scenario 7: '4 כוכבים' saved as level='יוקרתי', never as a 4-unit budget",
      (tu7.get("lodging") or {}).get("details", {}).get("level") == "יוקרתי"
      and (tu7.get("lodging") or {}).get("details", {}).get("budget") is None)

# --- 8. "no limit" -> level='אין העדפה', no numeric budget invented (#91) ---
member8 = _make_member("qa-014a-lodging-s8@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "budget": None, "level": "אין העדפה", "confidence": "high", "also_mentioned": None, "correction": None,
})):
    state8 = dict(LODGING_STATE_BASE)
    state8["lodging"] = {"details": {"type": "מלון", "rooms": 1}}
    state8["guided"] = {"current_question": "lodging_budget_or_level", "attempts": 0,
                         "answered": ["lodging_type", "lodging_rooms", "lodging_bathrooms", "lodging_locations"]}
    r8 = _post("אין הגבלה", [], state8, member8)
tu8 = r8.get("trip_update") or {}
check("scenario 8: 'no limit' saved as level='אין העדפה', no numeric budget",
      (tu8.get("lodging") or {}).get("details", {}).get("level") == "אין העדפה"
      and (tu8.get("lodging") or {}).get("details", {}).get("budget") is None)

# --- 9. also_mentioned: answering type also volunteers rooms+bathrooms ---
member9 = _make_member("qa-014a-lodging-s9@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "value": "דירה", "confidence": "high",
    "also_mentioned": {"lodging_rooms": {"value": 3}, "lodging_bathrooms": {"value": 2}},
    "correction": None,
})):
    state9 = dict(LODGING_STATE_BASE)
    state9["guided"] = {"current_question": "lodging_type", "attempts": 0, "answered": []}
    r9 = _post("דירה עם 3 חדרים ו-2 חדרי רחצה", [], state9, member9)
tu9 = r9.get("trip_update") or {}
check("scenario 9: type, rooms AND bathrooms all filled from one answer via also_mentioned",
      (tu9.get("lodging") or {}).get("details", {}).get("type") == "דירה"
      and (tu9.get("lodging") or {}).get("details", {}).get("rooms") == 3
      and (tu9.get("lodging") or {}).get("details", {}).get("bathrooms") == 2)
check("scenario 9: rooms+bathrooms questions are skipped (already answered)",
      "lodging_rooms" in ((tu9.get("guided") or {}).get("answered") or [])
      and "lodging_bathrooms" in ((tu9.get("guided") or {}).get("answered") or [])
      and (tu9.get("guided") or {}).get("current_question") == "lodging_locations")

# --- 10. correction after lodging search already "complete" -> reopens
#     LODGING (never flights) and sets a confirmation hint ---
member10 = _make_member("qa-014a-lodging-s10@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "value": 3, "confidence": "high", "also_mentioned": None,
    "correction": {"field": "lodging_rooms", "old": 2, "new": 3},
})):
    state10 = dict(LODGING_STATE_BASE)
    state10["session_status"] = {"flights": "complete", "lodging": "complete", "car": "pending", "trip_planning": "pending"}
    state10["lodging"] = {"details": {"type": "דירה", "rooms": 2, "bathrooms": 1, "locations": "אין העדפה", "budget": 150}}
    state10["guided"] = {"current_question": "lodging_rooms", "attempts": 0,
                          "answered": ["lodging_type", "lodging_bathrooms", "lodging_locations", "lodging_budget_or_level"]}
    r10 = _post("רגע, בעצם שלושה חדרים", [], state10, member10)
tu10 = r10.get("trip_update") or {}
check("scenario 10: rooms corrected to 3",
      (tu10.get("lodging") or {}).get("details", {}).get("rooms") == 3)
check("scenario 10: the hint tells Tinkerbell to confirm the update, naming the field",
      "מספר החדרים" in str(tu10.get("_guided_ask_hint") or "") and r10.get("reply") == "תשובה לדוגמה.")
# The dispatcher itself sets lodging back to "active" and ready_for_
# summary=False so a stale summary is never shown mid-turn; since every
# lodging field is genuinely filled again right after, a later pass
# correctly recomputes the session back to "complete" - ready_for_summary
# staying False is what actually matters (never flights, which this
# correction never touched).
check("scenario 10: ready_for_summary cleared by the correction, flights left untouched",
      tu10.get("ready_for_summary") is False
      and (tu10.get("session_status") or {}).get("flights") == "complete")

# --- 11. "אין לי מושג" twice -> attempts increments, then the loop guard
#     skips the field on the second unclear in a row (Carmit's explicit
#     directive, Copenhagen stage-1 run-3: the same question must never
#     repeat verbatim forever - see _guided_skip_hint) ---
member11 = _make_member("qa-014a-lodging-s11@example.com")
unclear = {"status": "unclear", "value": None, "confidence": "low", "also_mentioned": None, "correction": None}
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory(unclear)):
    state11 = dict(LODGING_STATE_BASE)
    state11["guided"] = {"current_question": "lodging_type", "attempts": 0, "answered": []}
    r11a = _post("אין לי מושג", [], state11, member11)
    tu11a = r11a.get("trip_update") or {}
    state11b = dict(LODGING_STATE_BASE)
    state11b["guided"] = tu11a.get("guided")
    r11b = _post("אין לי מושג", [], state11b, member11)
tu11b = r11b.get("trip_update") or {}
check("scenario 11: attempts incremented to 1 after the first 'no idea' - still on lodging_type",
      (tu11a.get("guided") or {}).get("attempts") == 1
      and (tu11a.get("guided") or {}).get("current_question") == "lodging_type"
      and "[" not in str(tu11a.get("_guided_ask_hint") or ""))
check("scenario 11: the loop guard fires on the SECOND 'no idea' in a row - "
      "lodging_type is skipped (marked answered, never actually known) and "
      "the dispatcher moves on to the next lodging field, attempts reset",
      "lodging_type" in ((tu11b.get("guided") or {}).get("answered") or [])
      and (tu11b.get("guided") or {}).get("current_question") == "lodging_rooms"
      and (tu11b.get("guided") or {}).get("attempts") == 0)
check("scenario 11: the skip hint never repeats the same question verbatim - "
      "it explicitly moves on, and never shows buttons",
      "לינה" in str(tu11b.get("_guided_ask_hint") or "")
      and "[" not in str(tu11b.get("_guided_ask_hint") or ""))

# --- 12. other_topic during a lodging question -> question stays open,
#     no hint forced onto an unrelated reply ---
member12 = _make_member("qa-014a-lodging-s12@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "other_topic", "value": None, "confidence": "low", "also_mentioned": None, "correction": None,
})):
    state12 = dict(LODGING_STATE_BASE)
    state12["guided"] = {"current_question": "lodging_type", "attempts": 0, "answered": []}
    r12 = _post("כמה עולה שכירות הרכב?", [], state12, member12)
tu12 = r12.get("trip_update") or {}
check("scenario 12: lodging_type question stays open",
      (tu12.get("guided") or {}).get("current_question") == "lodging_type")
# Dry-run 3 (Shaked, 22.10.2026): reversed from the original expectation
# here - "no hint forced, normal routing handles it" silently stopped the
# still-open question from ever being asked again across an unrelated
# turn (seen live for accessibility across turns 1-3 in B/C/E). A
# genuinely open current_question still gets its own plain hint rebuilt
# fresh every turn, never a NEW redirect and never forced wording.
check("scenario 12: the still-open lodging_type question gets its own "
      "hint rebuilt, even on this unrelated aside - never left with no "
      "steering at all",
      "איזה סוג לינה מתאים" in str(tu12.get("_guided_ask_hint") or ""))

# --- 13. broken model JSON -> falls back to the existing regex, no crash ---
member13 = _make_member("qa-014a-lodging-s13@example.com")
with patch.object(chat, "_post_claude", side_effect=lambda *a, **kw: (
        "{}" if kw.get("source") == "state_extractor"
        else ("not valid json {{{" if kw.get("source") == "guided_extract" else "תשובה לדוגמה.")
)):
    state13 = dict(LODGING_STATE_BASE)
    state13["guided"] = {"current_question": "lodging_type", "attempts": 0, "answered": []}
    r13 = _post("דירה", type_question_history, state13, member13)
tu13 = r13.get("trip_update") or {}
check("scenario 13: broken guided JSON never crashes the turn",
      r13.get("status") == "success")
check("scenario 13: falls back to the existing regex and still fills the type correctly",
      (tu13.get("lodging") or {}).get("details", {}).get("type") == "דירה")

# --- 14. route auto-fill: >=2 bases pre-satisfies lodging_locations before
#     the guided question ever reaches it; a single-base route never does
#     (#93, the Rome bug - ported here as a direct unit check) ---
state_multi_route = {"lodging": {"details": {}}, "trip_planning": {"details": {"route": [{"base": "רומא"}, {"base": "פירנצה"}]}}}
resolved_multi = chat._resolve_lodging_locations_from_route(state_multi_route)
check("scenario 14a: a genuine multi-stop route still auto-fills lodging.details.locations",
      resolved_multi.get("lodging", {}).get("details", {}).get("locations") == "רומא, פירנצה")

state_single_route = {"lodging": {"details": {}}, "trip_planning": {"details": {"route": [{"base": "הר הפלטינו"}]}}}
resolved_single = chat._resolve_lodging_locations_from_route(state_single_route)
check("scenario 14b: a single-base route never auto-fills lodging.details.locations (Rome bug #93)",
      not resolved_single.get("lodging", {}).get("details", {}).get("locations"))

# --- 15. no-buttons rule across the generic hint builders for every
#     lodging field, at every attempt stage ---
for field in chat._LODGING_GUIDED_SUBFIELDS:
    check(f"no-buttons rule: {field} fresh-ask hint never contains '['",
          "[" not in chat._guided_ask_hint(field, 0))
    check(f"no-buttons rule: {field} retry hint never contains '['",
          "[" not in chat._guided_ask_hint(field, 1))
confirm_desc_sample = "2 חדרים"
check("no-buttons rule: a lodging confirm hint never contains '['",
      "[" not in chat._guided_confirm_hint("lodging_rooms", confirm_desc_sample))
check("no-buttons rule: a lodging correction hint never contains '['",
      "[" not in chat._guided_correction_hint("מספר החדרים", confirm_desc_sample))

# --- 16. (Shaked, 2026-10-17, regression against 8a58d4e, same root cause
#     as #75/#76) Model call fails while a LODGING subfield is the live
#     field, on a message that also carries dates+travelers facts (both
#     still unresolved) - realistic once "lodging" is combined with the
#     already-approved "dates,travelers" in the same env var. Both must
#     still get filled via the widened regex fallback, not just the live
#     lodging field. ---
os.environ["GUIDED_EXTRACTION_STEPS"] = "dates,travelers,lodging"
member16 = _make_member("qa-014a-lodging-s16@example.com")
with patch.object(chat, "_post_claude", side_effect=lambda *a, **kw: (
        "{}" if kw.get("source") == "state_extractor"
        else (_ for _ in ()).throw(RuntimeError("simulated model failure")) if kw.get("source") == "guided_extract"
        else "תשובה לדוגמה."
)):
    state16 = {k: v for k, v in LODGING_STATE_BASE.items() if k not in ("dates", "travelers")}
    state16["guided"] = {"current_question": "lodging_type", "attempts": 0, "answered": []}
    r16 = _post("מלון, וטסים בין 10.11.2026 ל-15.11.2026 שני מבוגרים", [], state16, member16)
tu16 = r16.get("trip_update") or {}
check("scenario 16 (Shaked regression): lodging-field model failure never crashes the request",
      r16.get("status") == "success")
check("scenario 16 (Shaked regression): dates still gets filled via the widened regex fallback",
      (tu16.get("dates") or {}).get("departure") == "2026-11-10")
check("scenario 16 (Shaked regression): travelers still gets filled via the widened regex fallback",
      (tu16.get("travelers") or {}).get("adults") == 2)
check("scenario 16 (Shaked regression): current_question stays 'lodging_type' (still unanswered, no crash)",
      (tu16.get("guided") or {}).get("current_question") == "lodging_type")
check("scenario 16 (Shaked regression): a hint is still set so Tinkerbell asks in her own words",
      bool(tu16.get("_guided_ask_hint")))

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE email LIKE 'qa-014a-lodging-%@example.com'")
    conn.commit()

os.environ.pop("GUIDED_EXTRACTION_STEPS", None)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL 014A-LODGING GUIDED-EXTRACTION TESTS PASSED")
