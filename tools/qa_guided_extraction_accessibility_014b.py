"""QA for task 014b (plan 014, accessibility question - business owner's
decision 2026-10-17, relayed by Shlomo: "נגישות בשאלת השיחה גם צריך לקדם
אותה. זה חשוב"): one yes/no accessibility question asked right after the
travelers question resolves, with a single open follow-up only when the
customer says "yes" without a detail yet. Builds on 014a's same flag,
`guided` state field and extraction method (model-based JSON, never a
regex phrase list).

Spec: product/dev-tasks/014b-accessibility-question.md (ofek branch,
commit 68e5ab9), section 7's 8-item test list.

Run: python3 tools/qa_guided_extraction_accessibility_014b.py
"""
import os
import re
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
            ("QA 014b Accessibility", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def _post(message, history, trip_state, member_id):
    with client.session_transaction() as sess:
        sess["member_id"] = member_id
    r = client.post("/api/ariella/chat-clean", json={
        "message": message, "history": history, "trip_state": trip_state,
    })
    return r.get_json()


ROME_STATE_BASE = {
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
# Zero-regression (spec section 7): the flag's existing dates/travelers
# behavior, and everything without the flag, is untouched by adding the
# third field.
# =====================================================================
os.environ.pop("GUIDED_EXTRACTION_STEPS", None)
check("flag unset -> accessibility never engages either",
      chat._guided_extraction_steps() == set())
check("_accessibility_hint_text is a no-op with the flag off, even if the state somehow has needed=True",
      chat._accessibility_hint_text({"active_session": "lodging", "accessibility": {"needed": True, "needs": ["wheelchair"]}}) == "")

os.environ["GUIDED_EXTRACTION_STEPS"] = "dates,travelers,accessibility"
check("flag set -> _guided_extraction_steps() covers all three fields",
      chat._guided_extraction_steps() == {"dates", "travelers", "accessibility"})

# --- Ordering: accessibility is only asked once dates+travelers are both
#     already known, never before (spec section 3, "right after travelers") ---
member_order = _make_member("qa-014b-order@example.com")
with patch.object(chat, "_post_claude", side_effect=lambda *a, **kw: (
        "{}" if kw.get("source") == "state_extractor" else "תשובה לדוגמה."
)):
    state_order = dict(ROME_STATE_BASE)
    state_order["guided"] = {"current_question": None, "attempts": 0, "answered": []}
    r_order = _post("עוד שאלה כלשהי", [], state_order, member_order)
tu_order = r_order.get("trip_update") or {}
check("ordering: with dates+travelers already known, accessibility is the next guided question asked",
      r_order.get("reply") == chat._GUIDED_QUESTION_TEXT["accessibility"]
      and (tu_order.get("guided") or {}).get("current_question") == "accessibility")

# --- 1. Family with a stroller: "כן, יש עגלה" answered with detail in one
#     turn -> needs=[stroller], answered immediately, no follow-up ---
member1 = _make_member("qa-014b-s1@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "needed": True, "needs": ["stroller"], "details": "עגלת תינוק",
    "confidence": "high", "also_mentioned": None, "correction": None,
})):
    state1 = dict(ROME_STATE_BASE)
    state1["guided"] = {"current_question": "accessibility", "attempts": 0, "answered": ["dates", "travelers"]}
    r1 = _post("כן, יש לנו עגלה", [], state1, member1)
tu1 = r1.get("trip_update") or {}
acc1 = tu1.get("accessibility") or {}
check("scenario 1: needed=True and needs=['stroller'] captured in one turn",
      acc1.get("needed") is True and acc1.get("needs") == ["stroller"])
check("scenario 1: accessibility marked answered - no further question asked this turn",
      "accessibility" in ((tu1.get("guided") or {}).get("answered") or [])
      and r1.get("reply") != chat._GUIDED_ACCESSIBILITY_DETAIL_TEXT)

# --- 2. Wheelchair mentioned unprompted while answering the travelers
#     question -> also_mentioned fills it, question is skipped entirely ---
member2 = _make_member("qa-014b-s2@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "adults": 2, "children": 0, "child_ages": [], "child_genders": [],
    "infants": None, "confidence": "high",
    "also_mentioned": {
        "dates": None,
        "accessibility": {"needed": True, "needs": ["wheelchair"], "details": "אבא בכיסא גלגלים"},
    },
    "correction": None,
})):
    state2 = dict(ROME_STATE_BASE)
    state2.pop("travelers", None)
    state2["guided"] = {"current_question": "travelers", "attempts": 0, "answered": ["dates"]}
    r2 = _post("אני ואבא שלי, הוא בכיסא גלגלים", [], state2, member2)
tu2 = r2.get("trip_update") or {}
acc2 = tu2.get("accessibility") or {}
check("scenario 2: accessibility filled via also_mentioned from the travelers answer",
      acc2.get("needed") is True and acc2.get("needs") == ["wheelchair"])
check("scenario 2: accessibility question is skipped (already in answered, never asked separately)",
      "accessibility" in ((tu2.get("guided") or {}).get("answered") or [])
      and (tu2.get("guided") or {}).get("current_question") != "accessibility")

# --- 3. "לא" -> needed=False, continue with no further accessibility talk ---
member3 = _make_member("qa-014b-s3@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "needed": False, "needs": [], "details": None,
    "confidence": "high", "also_mentioned": None, "correction": None,
})):
    state3 = dict(ROME_STATE_BASE)
    state3["guided"] = {"current_question": "accessibility", "attempts": 0, "answered": ["dates", "travelers"]}
    r3 = _post("לא, תודה", [], state3, member3)
tu3 = r3.get("trip_update") or {}
acc3 = tu3.get("accessibility") or {}
check("scenario 3: 'no' sets needed=False",
      acc3.get("needed") is False)
check("scenario 3: accessibility marked answered, nothing further asked about it",
      "accessibility" in ((tu3.get("guided") or {}).get("answered") or []))

# --- 4. "כן" without detail -> ONE open follow-up, then the follow-up
#     reply fills needs/details and finally marks answered ---
member4 = _make_member("qa-014b-s4@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "needed": True, "needs": [], "details": None,
    "confidence": "high", "also_mentioned": None, "correction": None,
})):
    state4a = dict(ROME_STATE_BASE)
    state4a["guided"] = {"current_question": "accessibility", "attempts": 0, "answered": ["dates", "travelers"]}
    r4a = _post("כן", [], state4a, member4)
tu4a = r4a.get("trip_update") or {}
check("scenario 4a: 'yes' with no detail yet gets the ONE open follow-up, not a repeat of the yes/no",
      r4a.get("reply") == chat._GUIDED_ACCESSIBILITY_DETAIL_TEXT)
check("scenario 4a: accessibility stays open (not yet in answered)",
      "accessibility" not in ((tu4a.get("guided") or {}).get("answered") or [])
      and (tu4a.get("guided") or {}).get("current_question") == "accessibility")

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "needed": True, "needs": ["reduced_mobility"], "details": "קושי בהליכה ארוכה",
    "confidence": "high", "also_mentioned": None, "correction": None,
})):
    state4b = dict(ROME_STATE_BASE)
    state4b["guided"] = tu4a.get("guided")
    state4b["accessibility"] = tu4a.get("accessibility")
    r4b = _post("קשה לנו ללכת מרחקים ארוכים", [], state4b, member4)
tu4b = r4b.get("trip_update") or {}
acc4b = tu4b.get("accessibility") or {}
check("scenario 4b: the follow-up's answer fills needs/details",
      acc4b.get("needs") == ["reduced_mobility"] and acc4b.get("details") == "קושי בהליכה ארוכה")
check("scenario 4b: now marked answered",
      "accessibility" in ((tu4b.get("guided") or {}).get("answered") or []))

# --- 5. Medical reason -> only the practical need is ever stored (the
#     code stores whatever the model returns verbatim; the no-diagnosis
#     rule lives in the extraction prompt, same architecture as the other
#     guided fields - this proves the code adds no diagnosis of its own
#     and doesn't leak the raw message text instead of the model's need). ---
member5 = _make_member("qa-014b-s5@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "needed": True, "needs": ["reduced_mobility"], "details": "קושי בהליכה ארוכה",
    "confidence": "high", "also_mentioned": None, "correction": None,
})):
    state5 = dict(ROME_STATE_BASE)
    state5["guided"] = {"current_question": "accessibility", "attempts": 0, "answered": ["dates", "travelers"]}
    r5 = _post("יש לי טרשת נפוצה וקשה לי ללכת", [], state5, member5)
tu5 = r5.get("trip_update") or {}
acc5 = tu5.get("accessibility") or {}
check("scenario 5: only the practical need is stored, never the raw medical reason/diagnosis",
      acc5.get("details") == "קושי בהליכה ארוכה" and "טרשת" not in json.dumps(tu5, ensure_ascii=False))

# --- 6. New vacation -> accessibility is cleared, the question is asked
#     again (vacation-scoped field, never carried to a future vacation) ---
fresh = chat._reset_stale_trip_state(
    {"accessibility": {"asked": True, "needed": True, "needs": ["stroller"]}, "dates": {"departure": "2026-01-01"}},
    "חופשה חדשה",
)
check("scenario 6: a reset vacation drops 'accessibility' entirely - never carried from one vacation to the next",
      "accessibility" not in fresh)

# --- 7. one-option rule (iron rule, 2026-10-16): the accessibility
#     question is yes/no about ONE thing, never "א או ב" ---
import re as _re_rule7


def _is_single_option_or_open(text):
    text = str(text or "")
    question_part = _re_rule7.sub(r"\s*\[[^\]]*\]", "", text).strip()
    if "למשל" in question_part:
        return True
    return " או " not in question_part


for key_name in ("accessibility",):
    for label, mapping in (("question", chat._GUIDED_QUESTION_TEXT), ("retry", chat._GUIDED_UNCLEAR_RETRY_TEXT), ("choice", chat._GUIDED_CHOICE_OPTIONS)):
        check(f"one-option rule: accessibility {label} text has no bare 'X או Y?' inside the question",
              _is_single_option_or_open(mapping[key_name]))
check("one-option rule: the open detail follow-up is a plain open question, not a forced choice",
      _is_single_option_or_open(chat._GUIDED_ACCESSIBILITY_DETAIL_TEXT))

# --- 8. service-specific phrasing (spec section 5): the hint text changes
#     with active_session, and never fires with no confirmed need ---
need_state = {"accessibility": {"needed": True, "needs": ["wheelchair"], "details": "כיסא גלגלים"}}
for session, must_contain in (
    ("flight", "ליווי"),
    ("trip_planning", "הליכה"),
    ("lodging", "נגיש"),
    ("car", "עגלה"),
):
    hint = chat._accessibility_hint_text(dict(need_state, active_session=session))
    check(f"service hint for '{session}' mentions the right accommodation ('{must_contain}')",
          must_contain in hint)
check("service hint is empty when needed is not True",
      chat._accessibility_hint_text({"accessibility": {"needed": False}, "active_session": "lodging"}) == "")
check("service hint is empty with no accessibility state at all",
      chat._accessibility_hint_text({"active_session": "lodging"}) == "")

# --- 9. privacy policy copy (spec section 6) ---
privacy_src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "privacy.html"), encoding="utf-8").read()
check("privacy policy (Hebrew): accessibility is scoped to the one vacation and never saved",
      "ישמש רק לחיפוש של אותה חופשה" in privacy_src and "לא עובר לחופשה הבאה" in privacy_src)
check("privacy policy (English): same accessibility-scoping sentence present",
      "used only to search for that one vacation" in privacy_src)

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE email LIKE 'qa-014b-%@example.com'")
    conn.commit()

os.environ.pop("GUIDED_EXTRACTION_STEPS", None)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL 014B ACCESSIBILITY TESTS PASSED")
