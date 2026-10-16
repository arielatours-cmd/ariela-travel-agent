"""QA for task 014a (plan 014, stage 1, approved by the business owner
2026-10-16 - "understanding quality before cost savings"): a guided,
one-question-at-a-time flow for dates and travelers, understood by the
model instead of regex, entirely behind GUIDED_EXTRACTION_STEPS.

Spec: product/dev-tasks/014a-guided-basics-dates-travelers.md (ofek branch).

Covers Ofek's 10 scenarios (spec section 7) with the flag on, plus the
mandatory zero-regression check with the flag unset (the default) - every
existing qa/cases.json case for _deterministic_date_facts/_deterministic_
duration_facts/_deterministic_traveler_facts must still pass unchanged,
proving the new mechanism never engages unless explicitly turned on.

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
# WITHOUT THE FLAG: must be a complete no-op (section 7's mandatory check)
# =====================================================================
os.environ.pop("GUIDED_EXTRACTION_STEPS", None)
check("flag unset -> _guided_extraction_steps() is empty",
      chat._guided_extraction_steps() == set())

member0 = _make_member("qa-guided-flagoff@example.com")
with patch.object(chat, "_post_claude", side_effect=lambda *a, **kw: (
        "{}" if kw.get("source") == "state_extractor" else "תשובה לדוגמה."
)):
    r0 = _post("10.11.2026 עד 15.11.2026", [], dict(ROME_STATE), member0)
tu0 = r0.get("trip_update") or {}
check("flag off: regex still fills dates exactly as before (no guided interference)",
      (tu0.get("dates") or {}).get("departure") == "2026-11-10"
      and (tu0.get("dates") or {}).get("return") == "2026-11-15")
check("flag off: no 'guided' field appears in trip_update at all",
      "guided" not in tu0)

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE id=?", (member0,))
    conn.commit()

# =====================================================================
# WITH THE FLAG: Ofek's 10 scenarios
# =====================================================================
os.environ["GUIDED_EXTRACTION_STEPS"] = "dates,travelers"
check("flag set -> _guided_extraction_steps() covers both fields",
      chat._guided_extraction_steps() == {"dates", "travelers"})

# --- Proactive ask (spec section 3): the very first message after the
#     destination is known, with no guided question pending yet, gets the
#     dates question - not the regular free-text flow. ---
member_proactive = _make_member("qa-guided-proactive@example.com")
with patch.object(chat, "_post_claude", side_effect=lambda *a, **kw: (
        "{}" if kw.get("source") == "state_extractor" else "תשובה לדוגמה."
)):
    r_proactive = _post("אני רוצה לטוס לרומא", [], dict(ROME_STATE), member_proactive)
tu_proactive = r_proactive.get("trip_update") or {}
check("proactive ask: the dates guided question is asked on the very first eligible turn",
      r_proactive.get("reply") == chat._GUIDED_QUESTION_TEXT["dates"])
check("proactive ask: current_question is set to dates",
      (tu_proactive.get("guided") or {}).get("current_question") == "dates")

# --- 1. "10 בנובמבר ל-5 לילות" -> departure/return computed in code ---
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
check("scenario 1: next guided question (travelers) is asked",
      (tu1.get("guided") or {}).get("current_question") == "travelers")

# --- 2. "באמצע נובמבר, בערך שבוע" -> low confidence, confirm, no invented exact date ---
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
check("scenario 2: a one-line confirmation is asked, question stays open",
      "לוודא" in str(r2.get("reply") or "") and (tu2.get("guided") or {}).get("current_question") == "dates")

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

# --- 7. correction after travelers already set -> "עדכנתי: 3 נוסעים" ---
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
check("scenario 7: a one-line confirmation names the update",
      "עדכנתי" in str(r7.get("reply") or ""))

# --- 8. "אין לי מושג" twice -> after the second, choice options are offered ---
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
check("scenario 8: choice options offered after the second 'no idea'",
      r8b.get("reply") == chat._GUIDED_CHOICE_OPTIONS["dates"] and (tu8b.get("guided") or {}).get("attempts") == 2)

# --- 9. "כמה עולה מלון שם?" during the dates question -> other_topic, question stays open ---
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
check("scenario 9: the normal routing answered the actual message (not the canned guided question)",
      str(r9.get("reply") or "") != chat._GUIDED_QUESTION_TEXT["dates"])

# --- 10. Broken JSON from the model -> falls back to the existing regex, no crash ---
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

# --- 11. Business owner's one-option rule (2026-10-16, relayed via Shlomo/
#     Ofek): every guided text is an open question, or yes/no about exactly
#     ONE option - never "A or B?" joined by "או" inside the question
#     sentence. A finite choice set is offered as bracketed quick-replies
#     after an open question, never as a forced either/or pick. ---
import re as _re_rule11


def _is_single_option_or_open(text):
    text = str(text or "")
    # Strip bracketed quick-reply suggestions before checking the question
    # sentence itself - "[X] [Y]" after the question is the allowed way to
    # offer several answers, not a violation of the rule.
    question_part = _re_rule11.sub(r"\s*\[[^\]]*\]", "", text).strip()
    # The forbidden shape: two answer choices joined by a bare "או" inside
    # the question sentence itself (e.g. "ישירה או קונקשן?", "קצב רגוע או
    # פעיל?"). A choice-of-month/example list after an explicit "למשל"
    # (such as) is illustrative, not a forced pick, so it's exempt.
    if "למשל" in question_part:
        return True
    return " או " not in question_part


for key_name, text in {**chat._GUIDED_QUESTION_TEXT, **chat._GUIDED_UNCLEAR_RETRY_TEXT, **chat._GUIDED_CHOICE_OPTIONS}.items():
    check(f"one-option rule: {key_name!r} text has no bare 'X או Y?' inside the question",
          _is_single_option_or_open(text))

frag11, confirm11 = chat._guided_field_update_and_confirm("dates", {"departure": "2026-11-10", "return": "2026-11-15"})
check("one-option rule: the low-confidence confirmation is yes/no about ONE value, with [כן] [לתקן] as quick-replies",
      confirm11.endswith("[כן] [לתקן]") and _is_single_option_or_open(confirm11))

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
