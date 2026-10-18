"""QA for Shaked's stage-3 run-4 report (qa/reports/2026-10-18-stage3-run4.md,
branch shaked @eba2489, main @320d0e3) and Shlomo's two follow-up relays,
18.10.2026. 0/5 scenarios passed live. The urgent past-date bug (s3y2) was
fixed and shipped separately (PR #86, task/stage3-run4-fix1-date-rollover,
per Shlomo's explicit instruction to send it first on its own).

1. #85's reset-confirmation gate didn't fire live for genuine restart
   language ("בא לי בכלל לתכנן משהו אחר לגמרי", "עזבי את בודפשט, אני רוצה
   לחשוב על חופשה אחרת") even though a local test with a mocked model fired
   it correctly. Broadened EXTRACTOR_SYSTEM's restart_request rule - the
   examples were all explicit "start over" phrasing; these two real
   messages are just as clear in MEANING but far more indirect, and a model
   given only explicit examples can under-classify indirect ones.

2. Diagnostics for #1 and for Tuscany's guided-redirect miss ("לא קשורה
   לתקציב ללילה" fired again on "שתיים לפחות" answering a bathroom-count
   question - the same bug class #83's _guided_redirect_field fix targeted,
   Madrid/Milano, but it didn't catch this one). A first attempt logged
   both via plain logging.info - Shlomo's follow-up pointed out that has no
   value on this infrastructure at all: no agent has access to Render's own
   log stream. Replaced with record_diagnostic_event (ai_usage.py): a
   diagnostic-only ai_usage row per event (source="restart_signal"/
   "guided_redirect", real API calls' cost/token totals unaffected, same
   treatment as the pre-existing 'turn_total' rows), carrying exactly the
   fields Shlomo asked for (restart_request/evidence_verified for the
   first, current_question/candidates/redirect_target/extract_status for
   the second) and NEVER the customer's own message text - exportable via
   the new /admin/ai-usage/diagnostics.csv route so the business owner can
   download it and Shaked can analyze it without needing server log access.

3. General finding #6 (baggage per traveler-type): "וטרולי לכל ילד" ("a
   bag per CHILD") saved/summarized as per_person ("per every traveler,
   adults included") - a real schema gap, not a parsing bug: the baggage
   unit enum never had a "per_child" option at all, anywhere (the guided-
   extraction field's own primary schema, its regex fail-safe, or the
   label function) - per_person was the closest the model had, and it
   isn't the same fact. Added "per_child" as its own explicit unit value
   in all three places.

4. General finding #4 (Kyoto): trip_type stayed None for the whole
   conversation, looping "איזה סוג נסיעה זו?". Root cause traced to #85's
   own X/Y/Z opening-question fix: the opening question no longer NAMES
   the three categories ("חופשה רגילה, נסיעת עסקים, או חופשת סקי?"), so the
   customer's natural answer almost never echoes one of those category
   WORDS literally anymore - but EXTRACTOR_SYSTEM's trip_type rule still
   required the customer to have stated it "במפורש" (explicitly), which in
   practice meant one of those literal words. Loosened the rule to match
   TINKERBELL_SYSTEM's own standing instruction to classify trip_type from
   the customer's free-form description of the trip's purpose (leisure/
   work/skiing) - still forbidding any guess from destination/dates/
   travelers alone, just no longer requiring a magic word.

5. Per Shlomo's second follow-up: two remaining items from the report,
   addressed at the prompt/instruction level only - IMPORTANT: neither can
   be verified by this offline QA suite, only by a real live-site test
   (Shlomo's own explicit instruction when a fix is prompt-only). Flagged
   here, not claimed as confirmed-fixed:
   (a) "זה כבר רשום אצלי" said about a budget the customer never stated
       (Kyoto, V3) - no existing instruction caused this; it was
       Tinkerbell's own free improvisation with nothing telling her not to
       claim a fact is already known when it ISN'T in state. Added a new
       general rule, the explicit mirror of the existing "never re-ask a
       known fact" rule: never claim/imply a fact is already recorded
       unless it is genuinely present in the current state - decided by
       state alone, never by how the conversation history "feels".
   (b) Remaining X/Y-shaped questions (V5: "יש לכם שדה תעופה מועדף ליעד, או
       שנבדוק מה יש לליובליאנה עצמה?") - an "offer X, or we'll default to Y"
       framing that the existing one-question/no-X-or-Y rule apparently
       didn't register as the same violation, since Y here is phrased as
       the system's own fallback rather than an equal alternative.
       Reinforced the existing rule to name this framing explicitly as the
       same forbidden pattern. V1/V3's other symptoms (a leading/
       suggestive bathroom-count question, broken-Hebrew phrasing like
       "לנוסעת של 2"/"מצטיינת לקחת 4X4") are NOT addressed this round - no
       specific instruction was traced as their cause, and guessing at a
       fix without being able to verify it live risks making things worse.

Run: python3 tools/qa_stage3_run4_root_causes.py
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
import ai_usage
import app as app_module
from werkzeug.security import generate_password_hash

flask_client = app_module.app.test_client()

DB = database.DB_PATH
FAILED = []


def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA Stage3 Run4", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# =====================================================================
# 1. Restart-signal instruction broadened + diagnostic logging, without
#    the customer's own message text.
# =====================================================================
check("item 1: EXTRACTOR_SYSTEM's restart_request rule now covers indirect phrasing "
      "explicitly (not just explicit 'start over' wording)",
      "בא לי בכלל לתכנן משהו אחר לגמרי" in chat.EXTRACTOR_SYSTEM
      and "עזבי את" in chat.EXTRACTOR_SYSTEM)
check("item 1: the rule still requires understanding by MEANING, not matching specific sentences",
      "לפי המשמעות השלמה של המשפט" in chat.EXTRACTOR_SYSTEM)


# =====================================================================
# 2. record_diagnostic_event (ai_usage.py) - the DB-backed replacement for
#    the plain logging.info calls, per Shlomo's follow-up: no agent has
#    access to Render's own log stream, so a log line has zero value here.
# =====================================================================
check("record_diagnostic_event rejects an unknown event name (never silently records garbage)",
      ai_usage.record_diagnostic_event("not_a_real_event", {"x": 1}) is None
      and ai_usage.diagnostic_rows("not_a_real_event") == [])

ai_usage.set_ai_usage_context(member_id=None, is_test=True)
ai_usage.record_diagnostic_event("restart_signal", {"restart_request": True, "evidence_verified": False})
_restart_rows = ai_usage.diagnostic_rows("restart_signal", include_test=True)
check("restart_signal: a row was written and comes back via diagnostic_rows",
      bool(_restart_rows) and json.loads(_restart_rows[0]["details"]) == {"restart_request": True, "evidence_verified": False})

ai_usage.record_diagnostic_event("guided_redirect", {
    "current_question": "lodging_budget_or_level", "candidates": ["lodging_bathrooms"],
    "redirect_target": "lodging_bathrooms", "extract_status": "answered",
    "extract_confidence": "high", "fragment_written": True,
})
_redirect_rows = ai_usage.diagnostic_rows("guided_redirect", include_test=True)
check("guided_redirect: a row was written with exactly the fields Shlomo asked for, "
      "never the customer's own message text",
      bool(_redirect_rows)
      and json.loads(_redirect_rows[0]["details"]).get("redirect_target") == "lodging_bathrooms"
      and "message" not in json.loads(_redirect_rows[0]["details"]))
ai_usage.clear_ai_usage_context()

check("regression: diagnostic-only rows are excluded from usage_rows' real cost/token export",
      not any(r.get("source") in ai_usage.DIAGNOSTIC_EVENT_SOURCES for r in ai_usage.usage_rows(include_test=True)))
check("regression: diagnostic-only rows are excluded from usage_summary's totals/breakdowns",
      not any(s in ai_usage.DIAGNOSTIC_EVENT_SOURCES for s in ai_usage.usage_summary(include_test=True)["by_source"]))

# =====================================================================
# End-to-end: the real restart-gate code path writes a diagnostic row via
# this exact mechanism, with no customer message text in it anywhere.
# =====================================================================
m_diag = _make_member("qa-stage3run4-diag@example.com")
prague_state = {
    "destination": {"places": ["פראג"], "mode": "specific", "status": "known"},
    "destination_airports": ["PRG"],
    "travelers": {"adults": 2},
    "session_status": {"flights": "active", "lodging": "pending", "car": "pending", "trip_planning": "pending"},
    "active_session": "flights",
    "guided": {"current_question": "baggage", "attempts": 0, "answered": ["dates", "travelers"]},
}
database.save_ariella_conversation(m_diag, [
    {"role": "user", "content": "פראג, זוג, ביולי"},
    {"role": "assistant", "content": "קלטתי - פראג. איזו כבודה תצטרכו?"},
], prague_state)
_secret_message = "בא לי בכלל לתכנן משהו אחר לגמרי, רוצה טיול להרפתקאות קפריסין"


def _fake_post_claude_diag(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({"trip_update": {}, "restart_request": True, "restart_evidence": "בא לי בכלל לתכנן משהו אחר לגמרי"})
    if source == "tinkerbell_reply":
        return "תשובה לדוגמה."
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_diag):
    whatsapp_bridge.ariella_turn(m_diag, _secret_message)
_all_restart_rows = ai_usage.diagnostic_rows("restart_signal", include_test=True)
_this_turn_rows = [r for r in _all_restart_rows if r.get("member_id") == m_diag]
check("end-to-end: the real restart-gate turn above wrote its own restart_signal diagnostic row "
      "(tied to this specific member, not just any row in the table)",
      bool(_this_turn_rows) and json.loads(_this_turn_rows[0]["details"]).get("restart_request") is True)
check("end-to-end: no diagnostic row anywhere contains the customer's own message text",
      all(_secret_message not in (r.get("details") or "") for r in _all_restart_rows))

# =====================================================================
# The admin export route itself: /admin/ai-usage/diagnostics.csv - this is
# what Shlomo asked for ("so the business owner can export it").
# =====================================================================
_resp_bad = flask_client.get("/admin/ai-usage/diagnostics.csv?event=not_a_real_event")
check("admin route: an unknown ?event= is rejected with a clear error, not a silent empty CSV",
      _resp_bad.status_code == 400)
_resp_ok = flask_client.get("/admin/ai-usage/diagnostics.csv?event=restart_signal&include_test=1")
check("admin route: a valid ?event= returns a CSV with the expected diagnostic columns",
      _resp_ok.status_code == 200
      and _resp_ok.mimetype == "text/csv"
      and "details" in _resp_ok.get_data(as_text=True).splitlines()[0])


# =====================================================================
# 3. Baggage per_child unit - all three places.
# =====================================================================
r_child = chat._deterministic_baggage_facts("מזוודה אחת לכל ילד", traveler_count=4)
check("item 3: regex fail-safe recognizes 'per child' as its own unit, not per_person",
      r_child["flight"]["baggage_detail"]["checked_bag"]["unit"] == "per_child")
check("item 3: the label function distinguishes per_child from per_person",
      chat._checked_bag_label({"count": 1, "unit": "per_child"}) == "מזוודה אחת לכל ילד"
      and chat._checked_bag_label({"count": 3, "unit": "per_child"}) == "3 מזוודות לכל ילד")
fragment, desc = chat._guided_field_update_and_confirm("baggage", {
    "status": "answered", "no_baggage": False,
    "items": [{"type": "checked_bag", "count": 1, "unit": "per_child"}],
    "confidence": "high",
})
check("item 3: the guided-extraction field's own (primary) schema accepts per_child, "
      "not just the regex fail-safe",
      fragment.get("flight", {}).get("baggage_detail", {}).get("checked_bag", {}).get("unit") == "per_child")
check("item 3: EXTRACTOR_SYSTEM's guided baggage prompt documents per_child as its own, "
      "explicitly-distinct-from-per_person category",
      "per_child" in chat.EXTRACTOR_SYSTEM)

# Regressions: existing units still work exactly as before.
r_person = chat._deterministic_baggage_facts("מזוודה גדולה לכל אחד מאיתנו", traveler_count=4)
check("regression: per_person unit (no explicit digit) still recognized",
      r_person["flight"]["baggage_detail"]["checked_bag"]["unit"] == "per_person")
r_couple = chat._deterministic_baggage_facts("מזוודה אחת לכל זוג", traveler_count=4)
check("regression: per_couple unit still recognized",
      r_couple["flight"]["baggage_detail"]["checked_bag"]["unit"] == "per_couple")
r_total = chat._deterministic_baggage_facts("שתי מזוודות לכולנו", traveler_count=4)
check("regression: total/shared unit still recognized",
      r_total["flight"]["baggage_detail"]["checked_bag"]["unit"] == "total")


# =====================================================================
# 4. trip_type rule loosened to match the open-question flow (#85).
# =====================================================================
check("item 4: EXTRACTOR_SYSTEM's trip_type rule no longer requires a literal "
      "category word, and explains why (the open question never elicits one)",
      "כמעט לעולם לא ישתמש במילים" in chat.EXTRACTOR_SYSTEM)
check("item 4: the rule still forbids guessing trip_type from destination/dates/"
      "travelers alone when the customer never described the trip's purpose",
      "לנחש trip_type מ-destination/dates/travelers" in chat.EXTRACTOR_SYSTEM)


# =====================================================================
# 5. Prompt-only fixes (Shlomo's second follow-up) - NOT independently
#    verified live, only that the instruction text itself is present and
#    correctly placed, per his own explicit allowance for a prompt-only
#    fix ("אם התיקון הוא רק בפרומפט... זה ייבדק רק באתר החי").
# =====================================================================
check("item 5a: TINKERBELL_SYSTEM has a new rule, the explicit mirror of "
      "'never re-ask a known fact', forbidding the inverse: never claim a "
      "fact is already recorded unless it genuinely exists in state",
      "הכלל ההפוך חשוב באותה מידה" in chat.TINKERBELL_SYSTEM
      and "כבר רשום אצלך" in chat.TINKERBELL_SYSTEM)
check("item 5b: the X/Y rule explicitly names the 'offer X, or we default to Y' "
      "framing (V5: שדה תעופה מועדף... או שנבדוק) as the same forbidden pattern",
      "או שנבדוק/נבחר את Y בעצמנו" in chat.TINKERBELL_SYSTEM)


if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL STAGE3-RUN4-ROOT-CAUSES TESTS PASSED")
