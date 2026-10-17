"""QA for task 014b (plan 014, accessibility question) - rebuilt 2026-10-17
alongside #75's rework, after the business owner's two final decisions
(relayed via Shlomo/Ofek the same day) and Dan's (legal) corrected privacy
wording:

1. The code never sends a fixed sentence as the reply. It only tracks
   guided.current_question and sets a short hint in trip_update["
   _guided_ask_hint"]; Tinkerbell composes the actual yes/no question, the
   retry, the open "what would help" follow-up, and the confirmation
   herself, in her own main reply call (mocked here as "תשובה לדוגמה."
   throughout - this suite tests the STATE/HINT contract).
2. No quick-reply buttons anywhere, ever - including the yes/no itself.
3. Three legal/product constraints ride along on every accessibility hint:
   one yes/no question, non-medical illustrative examples only, and the
   code must never ask "why" or "what condition" (Dan, via Ofek).
4. Dan's corrected privacy-policy wording (not "never saved to your
   account" - the precise sentence he approved).

Builds on 014a's same flag, `guided` state field and extraction method
(model-based JSON, never a regex phrase list).

Spec: product/dev-tasks/014b-accessibility-question.md (ofek branch,
commit 68e5ab9), section 7's 8-item test list.

Run: python3 tools/qa_guided_extraction_accessibility_014b.py
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
# Zero-regression: the flag's existing dates/travelers behavior is
# untouched by adding accessibility. "Flag off" now means the Render env
# var is explicitly set to "" (the kill switch) since dates/travelers
# default ON via config.GUIDED_EXTRACTION_STEPS_DEFAULT.
# =====================================================================
os.environ["GUIDED_EXTRACTION_STEPS"] = ""
check("flag off (kill switch) -> accessibility never engages either",
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
check("ordering: with dates+travelers already known, accessibility is the next guided field queued",
      (tu_order.get("guided") or {}).get("current_question") == "accessibility")
check("ordering: a hint describing the yes/no accessibility question is set",
      "נגיש" in str(tu_order.get("_guided_ask_hint") or "") and "כן/לא" in str(tu_order.get("_guided_ask_hint") or ""))

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
      and not tu1.get("_guided_ask_hint"))

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

# --- 4. "כן" without detail -> ONE open follow-up hint (not a repeat of
#     the yes/no), then the follow-up reply fills needs/details and
#     finally marks answered ---
member4 = _make_member("qa-014b-s4@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "needed": True, "needs": [], "details": None,
    "confidence": "high", "also_mentioned": None, "correction": None,
})):
    state4a = dict(ROME_STATE_BASE)
    state4a["guided"] = {"current_question": "accessibility", "attempts": 0, "answered": ["dates", "travelers"]}
    r4a = _post("כן", [], state4a, member4)
tu4a = r4a.get("trip_update") or {}
check("scenario 4a: 'yes' with no detail yet gets an open-follow-up hint, not a repeat of the yes/no",
      "מה יעזור" in str(tu4a.get("_guided_ask_hint") or "") or "מה בדיוק" in str(tu4a.get("_guided_ask_hint") or ""))
check("scenario 4a: the follow-up hint explicitly forbids asking why/what medical condition",
      "בלי לשאול" in str(tu4a.get("_guided_ask_hint") or ""))
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

# --- 7. one-option + no-buttons rule (iron rule + business owner's final
#     decision, 2026-10-16/17): the accessibility hints never contain a
#     bracketed button, in any stage/attempt combination ---
check("no-buttons rule: fresh yes/no hint never contains '['",
      "[" not in chat._accessibility_ask_hint(False, 0))
check("no-buttons rule: yes/no retry hint never contains '['",
      "[" not in chat._accessibility_ask_hint(False, 1) and "[" not in chat._accessibility_ask_hint(False, 2))
check("no-buttons rule: open-detail hint never contains '['",
      "[" not in chat._accessibility_ask_hint(True, 0) and "[" not in chat._accessibility_ask_hint(True, 1))
check("legal rule: the hint explicitly forbids asking why/what medical condition",
      "למה" in chat._accessibility_ask_hint(False, 0) and "מצב רפואי" in chat._accessibility_ask_hint(False, 0))
check("legal rule: illustrative examples in the hint are non-medical (stroller/wheelchair/mobility)",
      "עגלת תינוק" in chat._accessibility_ask_hint(False, 0) and "כיסא גלגלים" in chat._accessibility_ask_hint(False, 0))

# --- 7b. (Shaked, 2026-10-17, regression against 8a58d4e, same root cause
#     as #75) Model call fails on the very FIRST turn, on a message
#     carrying BOTH dates and travelers facts at once, with neither
#     resolved yet (so "dates" is the live field, same as #75's repro) -
#     travelers must still get filled via the widened regex fallback,
#     not just the live field. accessibility has no legacy regex of its
#     own, so it isn't part of this particular check. ---
member7b = _make_member("qa-014b-s7b@example.com")
with patch.object(chat, "_post_claude", side_effect=lambda *a, **kw: (
        "{}" if kw.get("source") == "state_extractor"
        else (_ for _ in ()).throw(RuntimeError("simulated model failure")) if kw.get("source") == "guided_extract"
        else "תשובה לדוגמה."
)):
    state7b = {k: v for k, v in ROME_STATE_BASE.items() if k not in ("dates", "travelers")}
    r7b = _post("שלום, טסים זוג לרומא בין ה-10 ל-14 בנובמבר", [], state7b, member7b)
tu7b = r7b.get("trip_update") or {}
check("scenario 7b (Shaked regression): turn-1 model failure never crashes the request",
      r7b.get("status") == "success")
check("scenario 7b (Shaked regression): travelers still gets filled via the widened regex fallback",
      ((tu7b.get("travelers") or {}).get("adults") == 2))
check("scenario 7b (Shaked regression): current_question stays 'dates' (still unanswered, no crash)",
      (tu7b.get("guided") or {}).get("current_question") == "dates")
check("scenario 7b (Shaked regression): a hint is still set so Tinkerbell asks in her own words",
      bool(tu7b.get("_guided_ask_hint")))

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

# --- 9. privacy policy copy (Dan's corrected wording, spec section 6) ---
privacy_src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "privacy.html"), encoding="utf-8").read()
check("privacy policy (Hebrew): Dan's corrected wording is present verbatim",
      "נשמור רק את הצורך המעשי, בלי אבחנה או מצב רפואי" in privacy_src
      and "לא עובר לחופשה הבאה ולא נשמר בפרופיל שלכם" in privacy_src)
check("privacy policy (English): Dan's corrected wording is present verbatim",
      "never a diagnosis or medical condition" in privacy_src
      and "not carried over to a future vacation or saved to your profile" in privacy_src)
check("privacy policy no longer uses the imprecise 'never saved to your account' phrasing Dan flagged",
      "לעולם לא נשמר בחשבון" not in privacy_src)

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE email LIKE 'qa-014b-%@example.com'")
    conn.commit()

os.environ.pop("GUIDED_EXTRACTION_STEPS", None)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL 014B ACCESSIBILITY TESTS PASSED")
