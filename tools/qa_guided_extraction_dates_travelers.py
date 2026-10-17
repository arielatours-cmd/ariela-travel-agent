"""QA for task 014a (plan 014, stage 1) - rebuilt 2026-10-17 after Shaked
rejected the previous version (fa6210d-era #74/#75) with two blocking
findings, plus the business owner's two final decisions the same day:

1. (Shaked, blocking) A fact given in the very FIRST message was marked
   "answered" yet the canned question was asked again anyway - extraction
   only ran once a guided question had already been asked on a PRIOR turn.
   Fixed: extraction against the current message now always runs for
   whichever field is live, including on the very first turn.
2. (Shaked, blocking) When the model failed on that first turn, the old
   regex never ran either (same root cause) - nothing captured the
   message's facts at all. Fixed by the same change.
3. (Ofek/Shlomo, PRODUCT_RULES §2 "free conversation"): the code never
   sends a fixed sentence as Ariella's reply. It only sets guided.
   current_question and a short hint in trip_update["_guided_ask_hint"];
   Tinkerbell composes the actual question/retry/confirmation herself in
   her own main reply call (mocked here as "תשובה לדוגמה." throughout -
   this suite tests the STATE/HINT contract, not Tinkerbell's wording).
4. (business owner, final) No quick-reply buttons anywhere, ever - not
   even after repeated unclear answers.
5. (Shlomo) GUIDED_EXTRACTION_STEPS now defaults ON for approved fields
   via config.GUIDED_EXTRACTION_STEPS_DEFAULT - the Render env var is only
   an emergency override/kill-switch, so "flag off" tests now need to SET
   the env var to "" explicitly, not just leave it unset.

Run: python3 tools/qa_guided_extraction_dates_travelers.py
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
            ("QA Guided Extraction", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
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
# Default ON (Shlomo's request): with no env var at all, both fields are
# covered via config.GUIDED_EXTRACTION_STEPS_DEFAULT.
# =====================================================================
os.environ.pop("GUIDED_EXTRACTION_STEPS", None)
import config as _config
check("code-level default (config.GUIDED_EXTRACTION_STEPS_DEFAULT) covers dates+travelers",
      chat._guided_extraction_steps() == {"dates", "travelers"})
check("the Render env var, when actually set, overrides the code default (empty = kill switch)",
      (lambda: (os.environ.__setitem__("GUIDED_EXTRACTION_STEPS", ""), chat._guided_extraction_steps() == set(), os.environ.pop("GUIDED_EXTRACTION_STEPS", None))[1])())

# =====================================================================
# WITHOUT THE FLAG (env var explicitly set to "", the kill switch): a
# complete no-op, same as the old all-off default.
# =====================================================================
os.environ["GUIDED_EXTRACTION_STEPS"] = ""
member0 = _make_member("qa-guided-flagoff@example.com")
with patch.object(chat, "_post_claude", side_effect=lambda *a, **kw: (
        "{}" if kw.get("source") == "state_extractor" else "תשובה לדוגמה."
)):
    r0 = _post("10.11.2026 עד 15.11.2026", [], dict(ROME_STATE), member0)
tu0 = r0.get("trip_update") or {}
check("flag off (kill switch): regex still fills dates exactly as before (no guided interference)",
      (tu0.get("dates") or {}).get("departure") == "2026-11-10"
      and (tu0.get("dates") or {}).get("return") == "2026-11-15")
check("flag off: no 'guided' field appears in trip_update at all",
      "guided" not in tu0)
check("flag off: no guided hint ever set",
      "_guided_ask_hint" not in tu0)

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE id=?", (member0,))
    conn.commit()

# =====================================================================
# WITH THE FLAG explicitly set (dates,travelers - same as the default,
# set explicitly here so every scenario below is self-contained)
# =====================================================================
os.environ["GUIDED_EXTRACTION_STEPS"] = "dates,travelers"
check("flag set -> _guided_extraction_steps() covers both fields",
      chat._guided_extraction_steps() == {"dates", "travelers"})

# --- Turn-1 fix (Shaked's blocking finding #1): a fact already given in
#     the very FIRST message (no guided question ever asked yet) is
#     recognized immediately - extraction runs against this message even
#     though current_question was never set before this turn. ---
member_turn1 = _make_member("qa-guided-turn1@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "departure": "2026-11-10", "return": "2026-11-14",
    "nights": None, "period": None, "flexibility_days": None, "confidence": "high",
    "also_mentioned": {"travelers": {"adults": 2, "children": 0, "child_ages": [], "child_genders": []}},
    "correction": None,
})):
    r_turn1 = _post("שלום, טסים זוג לרומא בין ה-10 ל-14 בנובמבר", [], dict(ROME_STATE), member_turn1)
tu_turn1 = r_turn1.get("trip_update") or {}
check("turn-1 fix: dates filled on the very first message, no guided question ever asked before",
      (tu_turn1.get("dates") or {}).get("departure") == "2026-11-10"
      and (tu_turn1.get("dates") or {}).get("return") == "2026-11-14")
check("turn-1 fix: travelers filled too, via also_mentioned in the SAME first-message call",
      (tu_turn1.get("travelers") or {}).get("adults") == 2)
check("turn-1 fix: both fields marked answered - no redundant question about either",
      set((tu_turn1.get("guided") or {}).get("answered") or []) == {"dates", "travelers"})
check("turn-1 fix: nothing left to ask -> no guided hint set (normal conversation continues)",
      not tu_turn1.get("_guided_ask_hint"))

# --- Turn-1 fail-safe (Shaked's blocking finding #2): when the model
#     fails on the very first turn, the old regex still runs - previously
#     it silently captured nothing at all in this exact case. ---
member_turn1fail = _make_member("qa-guided-turn1fail@example.com")
with patch.object(chat, "_post_claude", side_effect=lambda *a, **kw: (
        "{}" if kw.get("source") == "state_extractor"
        else ("not valid json {{{" if kw.get("source") == "guided_extract" else "תשובה לדוגמה.")
)):
    r_turn1fail = _post("20.12.2026 עד 27.12.2026", [], dict(ROME_STATE), member_turn1fail)
tu_turn1fail = r_turn1fail.get("trip_update") or {}
check("turn-1 fail-safe: broken guided JSON on the FIRST turn still falls back to the regex and fills dates",
      (tu_turn1fail.get("dates") or {}).get("departure") == "2026-12-20"
      and (tu_turn1fail.get("dates") or {}).get("return") == "2026-12-27")
check("turn-1 fail-safe: a hint is still set so Tinkerbell tries in her own words regardless",
      bool(tu_turn1fail.get("_guided_ask_hint")))

# --- 1. "10 בנובמבר ל-5 לילות" -> departure/return computed in code,
#     advances to travelers with a hint (no fixed question text) ---
member1 = _make_member("qa-guided-s1@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "departure": "2026-11-10", "return": None, "nights": 5,
    "period": None, "flexibility_days": None, "confidence": "high",
    "also_mentioned": {"travelers": None}, "correction": None,
})):
    state1 = dict(ROME_STATE)
    state1["guided"] = {"current_question": "dates", "attempts": 0, "answered": []}
    r1 = _post("10 בנובמבר ל-5 לילות", [], state1, member1)
tu1 = r1.get("trip_update") or {}
check("scenario 1: departure=2026-11-10", (tu1.get("dates") or {}).get("departure") == "2026-11-10")
check("scenario 1: return computed as 2026-11-15 (5 nights, in code not the model)",
      (tu1.get("dates") or {}).get("return") == "2026-11-15")
check("scenario 1: next guided question (travelers) is queued",
      (tu1.get("guided") or {}).get("current_question") == "travelers")
check("scenario 1: the hint describes travelers, not a fixed question",
      "נוסע" in str(tu1.get("_guided_ask_hint") or ""))
check("scenario 1: the reply is Tinkerbell's own (mocked) text, never a dict-literal question",
      r1.get("reply") == "תשובה לדוגמה.")

# --- 2. "באמצע נובמבר, בערך שבוע" -> low confidence, confirm hint, no
#     invented exact date ---
member2 = _make_member("qa-guided-s2@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "departure": None, "return": None, "nights": None,
    "period": "אמצע נובמבר", "flexibility_days": 7, "confidence": "low",
    "also_mentioned": {"travelers": None}, "correction": None,
})):
    state2 = dict(ROME_STATE)
    state2["guided"] = {"current_question": "dates", "attempts": 0, "answered": []}
    r2 = _post("באמצע נובמבר, בערך שבוע", [], state2, member2)
tu2 = r2.get("trip_update") or {}
check("scenario 2: low confidence -> no exact departure/return invented",
      not (tu2.get("dates") or {}).get("departure") and not (tu2.get("dates") or {}).get("return"))
check("scenario 2: a confirm hint is set, question stays open",
      "ודא" in str(tu2.get("_guided_ask_hint") or "") and (tu2.get("guided") or {}).get("current_question") == "dates")
check("scenario 2: confirm hint never offers buttons",
      "[" not in str(tu2.get("_guided_ask_hint") or ""))

# --- 3. "14-16 במרץ" -> 2 nights (regression: a previously-fixed bug in
#        the existing fallback regex - this task never touches it) ---
d3 = chat._deterministic_date_facts([], "רוצה לטוס ב-14-16 במרץ", {})
if d3.get("dates"):
    from datetime import date as _date
    dep3 = _date.fromisoformat(d3["dates"]["departure"])
    ret3 = _date.fromisoformat(d3["dates"]["return"])
    check("scenario 3: '14-16 במרץ' regex still gives exactly 2 nights (this fix doesn't touch the fallback regex)",
          (ret3 - dep3).days == 2)
else:
    check("scenario 3: '14-16 במרץ' regex still gives exactly 2 nights (this fix doesn't touch the fallback regex)",
          False)

# --- 4. "זוג עם ילדה בת 17" -> 2 adults, 1 child, ages=[17], genders=["female"] ---
member4 = _make_member("qa-guided-s4@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "adults": 2, "children": 1, "child_ages": [17],
    "child_genders": ["female"], "infants": None, "confidence": "high",
    "also_mentioned": {"dates": None}, "correction": None,
})):
    state4 = dict(ROME_STATE)
    state4["guided"] = {"current_question": "travelers", "attempts": 0, "answered": ["dates"]}
    state4["dates"] = {"departure": "2026-11-10", "return": "2026-11-15"}
    r4 = _post("זוג עם ילדה בת 17", [], state4, member4)
tu4 = r4.get("trip_update") or {}
check("scenario 4: adults=2, children=1, ages=[17], genders=['female']",
      (tu4.get("travelers") or {}).get("adults") == 2
      and (tu4.get("travelers") or {}).get("children") == 1
      and (tu4.get("travelers") or {}).get("child_ages") == [17]
      and (tu4.get("travelers") or {}).get("child_genders") == ["female"])

# --- 5. "אני והתאומים בני 7" -> 1 adult, 2 children, ages=[7,7] ---
member5 = _make_member("qa-guided-s5@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "adults": 1, "children": 2, "child_ages": [7, 7],
    "child_genders": [None, None], "infants": None, "confidence": "high",
    "also_mentioned": {"dates": None}, "correction": None,
})):
    state5 = dict(ROME_STATE)
    state5["guided"] = {"current_question": "travelers", "attempts": 0, "answered": ["dates"]}
    r5 = _post("אני והתאומים בני 7", [], state5, member5)
tu5 = r5.get("trip_update") or {}
check("scenario 5: adults=1, children=2, ages=[7,7]",
      (tu5.get("travelers") or {}).get("adults") == 1
      and (tu5.get("travelers") or {}).get("children") == 2
      and (tu5.get("travelers") or {}).get("child_ages") == [7, 7])

# --- 6. dates question answered with travelers also mentioned -> travelers skipped ---
member6 = _make_member("qa-guided-s6@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "departure": "2026-11-10", "return": "2026-11-15",
    "nights": None, "period": None, "flexibility_days": None, "confidence": "high",
    "also_mentioned": {"travelers": {"adults": 2, "children": 2, "child_ages": [5, 8], "child_genders": [None, None]}},
    "correction": None,
})):
    state6 = dict(ROME_STATE)
    state6["guided"] = {"current_question": "dates", "attempts": 0, "answered": []}
    r6 = _post("10.11, אני ובעלי ושני ילדים בני 5 ו-8", [], state6, member6)
tu6 = r6.get("trip_update") or {}
check("scenario 6: dates filled from the main answer",
      (tu6.get("dates") or {}).get("departure") == "2026-11-10")
check("scenario 6: travelers filled via also_mentioned",
      (tu6.get("travelers") or {}).get("adults") == 2 and (tu6.get("travelers") or {}).get("children") == 2)
check("scenario 6: travelers question is skipped (already answered)",
      "travelers" in ((tu6.get("guided") or {}).get("answered") or [])
      and (tu6.get("guided") or {}).get("current_question") != "travelers")

# --- 7. correction after travelers already set -> a confirmation hint
#     naming the update, never "עדכנתי את X." as a literal reply ---
member7 = _make_member("qa-guided-s7@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "adults": 3, "children": 0, "child_ages": [],
    "child_genders": [], "infants": None, "confidence": "high",
    "also_mentioned": {"dates": None},
    "correction": {"field": "adults", "old": 2, "new": 3},
})):
    state7 = dict(ROME_STATE)
    state7["guided"] = {"current_question": "travelers", "attempts": 0, "answered": ["dates"]}
    state7["travelers"] = {"adults": 2, "children": 0, "child_ages": [], "child_genders": []}
    r7 = _post("רגע, שלושה", [], state7, member7)
tu7 = r7.get("trip_update") or {}
check("scenario 7: travelers corrected to 3 adults",
      (tu7.get("travelers") or {}).get("adults") == 3)
check("scenario 7: the hint tells Tinkerbell to confirm the update in one sentence, not a fixed reply",
      "עדכן" in str(tu7.get("_guided_ask_hint") or "") and r7.get("reply") == "תשובה לדוגמה.")

# --- 8. "אין לי מושג" twice -> no buttons ever; attempts increments and
#     the hint explicitly asks for a different open phrasing + example ---
member8 = _make_member("qa-guided-s8@example.com")
unclear = {
    "status": "unclear", "departure": None, "return": None, "nights": None,
    "period": None, "flexibility_days": None, "confidence": "low",
    "also_mentioned": {"travelers": None}, "correction": None,
}
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory(unclear)):
    state8 = dict(ROME_STATE)
    state8["guided"] = {"current_question": "dates", "attempts": 0, "answered": []}
    r8a = _post("אין לי מושג", [], state8, member8)
    tu8a = r8a.get("trip_update") or {}
    state8b = dict(ROME_STATE)
    state8b["guided"] = tu8a.get("guided")
    r8b = _post("אין לי מושג", [], state8b, member8)
tu8b = r8b.get("trip_update") or {}
check("scenario 8: attempts incremented to 1 after the first 'no idea'",
      (tu8a.get("guided") or {}).get("attempts") == 1)
check("scenario 8: attempts incremented to 2 after the second 'no idea' - never buttons",
      (tu8b.get("guided") or {}).get("attempts") == 2 and "[" not in str(tu8b.get("_guided_ask_hint") or ""))
check("scenario 8: the retry hint explicitly asks for a different phrasing/example, never a repeat",
      "שונה" in str(tu8b.get("_guided_ask_hint") or "") or "אחר" in str(tu8b.get("_guided_ask_hint") or ""))

# --- 9. "כמה עולה מלון שם?" during the dates question -> other_topic,
#     question stays open, no hint forced onto an unrelated reply ---
member9 = _make_member("qa-guided-s9@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "other_topic", "departure": None, "return": None, "nights": None,
    "period": None, "flexibility_days": None, "confidence": "low",
    "also_mentioned": {"travelers": None}, "correction": None,
})):
    state9 = dict(ROME_STATE)
    state9["guided"] = {"current_question": "dates", "attempts": 0, "answered": []}
    r9 = _post("כמה עולה מלון שם?", [], state9, member9)
tu9 = r9.get("trip_update") or {}
check("scenario 9: dates question stays open (current_question unchanged)",
      (tu9.get("guided") or {}).get("current_question") == "dates")
check("scenario 9: no guided hint forced onto this unrelated message - normal routing handles it",
      not tu9.get("_guided_ask_hint"))

# --- 10. Broken JSON from the model on a FOLLOW-UP turn -> falls back to
#     the existing regex, no crash, and a hint is still set ---
member10 = _make_member("qa-guided-s10@example.com")
with patch.object(chat, "_post_claude", side_effect=lambda *a, **kw: (
        "{}" if kw.get("source") == "state_extractor"
        else ("not valid json at all {{{" if kw.get("source") == "guided_extract" else "תשובה לדוגמה.")
)):
    state10 = dict(ROME_STATE)
    state10["guided"] = {"current_question": "dates", "attempts": 0, "answered": []}
    r10 = _post("10.11.2026 עד 15.11.2026", [], state10, member10)
tu10 = r10.get("trip_update") or {}
check("scenario 10: broken guided JSON never crashes the turn",
      r10.get("status") == "success")
check("scenario 10: falls back to the existing regex and still fills the date correctly",
      (tu10.get("dates") or {}).get("departure") == "2026-11-10")

# --- 11. No buttons, ever, anywhere in the hint-building machinery -
#     scan every hint a representative set of calls can produce. ---
check("no-buttons rule: a fresh-ask hint never contains '['",
      "[" not in chat._guided_ask_hint("dates", 0))
check("no-buttons rule: a retry hint (attempts>=1) never contains '['",
      "[" not in chat._guided_ask_hint("dates", 1) and "[" not in chat._guided_ask_hint("travelers", 2))
check("no-buttons rule: a confirm hint never contains '['",
      "[" not in chat._guided_confirm_hint("dates", "יציאה ב-10.11.2026 וחזרה ב-15.11.2026"))
check("no-buttons rule: a correction hint never contains '['",
      "[" not in chat._guided_correction_hint("התאריכים", "יציאה ב-10.11.2026"))

# --- 12. (Shaked, 2026-10-17, regression against 8a58d4e) Model call fails
#     on the very FIRST turn, on a message carrying BOTH dates and
#     travelers facts at once ("טסים זוג לרומא בין ה-10 ל-14 בנובמבר"):
#     the fail-safe must widen regex_fallback_fields to every unanswered
#     guided field, not just the one live field ("dates"), or the other
#     field's regex gets silently suppressed too (it's nominally covered
#     by the flag, yet never actually attempted this turn) - exactly what
#     Shaked's own table showed happening to "travelers" across 4/5 of
#     her test messages. ---
member12 = _make_member("qa-guided-s12@example.com")
with patch.object(chat, "_post_claude", side_effect=lambda *a, **kw: (
        "{}" if kw.get("source") == "state_extractor"
        else (_ for _ in ()).throw(RuntimeError("simulated model failure")) if kw.get("source") == "guided_extract"
        else "תשובה לדוגמה."
)):
    r12 = _post("שלום, טסים זוג לרומא בין ה-10 ל-14 בנובמבר", [], dict(ROME_STATE), member12)
tu12 = r12.get("trip_update") or {}
check("scenario 12 (Shaked regression): turn-1 model failure never crashes the request",
      r12.get("status") == "success")
check("scenario 12 (Shaked regression): travelers still gets filled via the widened regex fallback",
      ((tu12.get("travelers") or {}).get("adults") == 2))
check("scenario 12 (Shaked regression): current_question stays 'dates' (still unanswered, no crash)",
      (tu12.get("guided") or {}).get("current_question") == "dates")
check("scenario 12 (Shaked regression): a hint is still set so Tinkerbell asks in her own words",
      bool(tu12.get("_guided_ask_hint")))

with sqlite3.connect(DB) as conn:
    conn.execute(
        "DELETE FROM members WHERE email LIKE 'qa-guided-%@example.com'"
    )
    conn.commit()

os.environ.pop("GUIDED_EXTRACTION_STEPS", None)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL GUIDED-EXTRACTION-DATES-TRAVELERS TESTS PASSED")
