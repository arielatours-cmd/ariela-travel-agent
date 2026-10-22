"""QA for Shaked's stage-1 run-7 bug A (severe, priority 1) - relayed by
Shlomo (21.10.2026):

"שינוי תאריך אחרי הסיכום לא נשמר (בנגקוק ובטומי, חמור): בנגקוק: 'רגע, אפשר
לדחות את כל הטיסה ביום אחד?' <- הסיכום הישן <- 'כן' <- אותו סיכום. בטומי:
'רגע, אפשר לצאת ב-5.6 ולחזור ב-9.6 במקום?' <- סיכום עם 04-08.06 <- 'כן' <-
שוב 04-08.06. השורש המשוער: רשת הביטחון missing-final-summary (~שורה
13828). כשכל התחומים סגורים, כל תשובה בלי 'מאשר' מוחלפת ב-
_final_summary_fallback_text. לכן תשובה לבקשת שינוי נדרסת בסיכום הישן. מה
צריך לקרות: אחרי הסיכום, בקשת שינוי של הלקוח מטופלת כמו באמצע השיחה (כמו
בקורפו, שעבר). תאריכים מפורשים נשמרים מיד, והסיכום שמוצג אחר כך נבנה
מה-state המעודכן."

Root cause confirmed by direct code reading: _all_domains_decided_now
(ariella_chat_clean.py, ~line 13744) stays True the instant dates were
last locked - it says nothing about whether THIS turn just reopened them.
The missing-final-summary safety net right after it (~line 13828) treated
ANY reply lacking "מאשר"/"חופשה נעימה" as a failure to produce the
mandatory final summary, including Tinkerbell's own CORRECT reply to a
genuine post-summary date-change request (a shift proposal awaiting
confirmation, or an acknowledgement of newly committed explicit dates) -
and replaced it with the stale _final_summary_fallback_text built from
the OLD dates. The customer's next "כן" then had nothing genuine to
confirm, since the real proposal text was never actually shown/recorded
in history - hence "same old summary" on both turns.

Fix: a new _post_summary_date_change_pending gate (scoped to dates only,
via the already-closed prior_dates - same scoping discipline used
elsewhere in this exact block) skips the entire missing-final-summary
safety net (both the forced Tinkerbell retry and the hard fallback
replace) whenever dates were just changed or put into a pending-
confirmation state THIS turn. Tinkerbell's own natural reply then reaches
the customer unmolested, exactly as it already does mid-conversation
(where _all_domains_decided_now was simply False and this safety net
never ran at all) - matching Shaked's own prescription verbatim.

Covers:
- Bangkok-shape: a relative shift request ("אפשר לדחות... ביום אחד?")
  post-summary proposes a pending candidate (old departure/return kept,
  needs_confirmation=True) and Tinkerbell's own proposal reply passes
  through untouched instead of being replaced by the stale summary.
- The following "כן" turn actually commits the shifted dates (reusing
  _accept_single_proposed_date_range, exactly as it already does
  mid-conversation), and that reply also passes through untouched.
- Batumi-shape: explicit new dates ("לצאת ב-5.6 ולחזור ב-9.6 במקום") with
  verified dates_evidence commit immediately (no confirmation step,
  mirroring Corfu/U5's own passing behavior) and the acknowledgement
  reply passes through untouched.
- Regression: the pre-existing "opposite failure" this safety net exists
  for (Haifa->Bangkok, Shaked's stage-2 finding) still fires when a reply
  genuinely fails to produce the final summary and dates are NOT part of
  what just changed this turn.

REWORK (Shaked's rejection of this PR's first version, 21.10.2026, relayed
by Shlomo): "מה שבדקה עובד, אבל התיקון חלקי." Three follow-up items, in
order:

(א) The gate was dates-only - a post-summary budget/baggage/traveler-count
change with a reply lacking "מאשר" ("רק לוודא - 4000 לאדם?") still got
stomped. First generalized to a structural per-fact before/after state
comparison (a fact counts only once it was ALREADY resolved before this
turn) - but Shaked's SECOND rejection (21.10.2026, on dfe869d) caught that
this still missed a genuine post-summary request that produces a
CLARIFYING question with nothing written to state yet ("אפשר להעלות קצת
את התקציב?" -> "לכמה תרצי להעלות?") - no fact changed this turn, so the
gate stayed closed and the clarifying question itself got stomped. Per
the business owner's decision (on Shaked's own proposal): the missing-
final-summary safety net exists ONLY to drive the conversation to the
FIRST real summary - once trip_update["final_summary_shown"] is set (or,
for an older saved conversation predating the flag, history already shows
the approval phrase), Tinkerbell's reply passes through as-is from then
on, regardless of what the current turn's state looks like. This replaces
the field-specific state-diff gate entirely.

(ב) The live failure may also be the EXTRACTOR itself never writing
differing dates/shift_days at all for a genuine post-summary change
request (pending Shaked's own diagnostics.csv review). Interim fix per
Shlomo's instruction: _post_summary_dates_context_hint gives the
extractor the same kind of explicit situational grounding
_connection_preference_pending_hint already gives for a different field -
once every domain is decided and dates are closed, the model is told the
exact dates already shown and that any further date mention is
necessarily a change request, never a verb list.

(ג) A bare "כן" was observed choosing the FIRST of several date options
Ariella displayed alongside an unrelated general yes/no confirm in the
same message. Two prompt-level fixes: TINKERBELL_SYSTEM now forbids
bundling a general yes/no confirm with presenting candidate_ranges in the
same message, and the guided_extract dates prompt now explicitly
instructs the model never to guess which of several pending candidates a
bare agreement selects (confidence:"low" instead).

Run: python3 tools/qa_post_summary_date_change.py
"""
import os
import sys
import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

import ariella_chat_clean as chat
import app as app_module
from werkzeug.security import generate_password_hash

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
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports,gender) "
            "VALUES(?,?,?,?,?,?,?,?)",
            ("QA Post Summary Date Change", email, generate_password_hash("Test1234!"),
             datetime.now(timezone.utc).isoformat(), "active", 0, "[]", "female"),
        )
        return cur.lastrowid


member = _make_member("qa-post-summary-date-change@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member

# All four domains already complete/declined - the real final-summary
# moment has already happened, exactly like Bangkok/Batumi after approval.
_ALL_DECIDED_STATE = {
    "trip_type": "vacation",
    "destination": {"places": ["בנגקוק"], "mode": "specific", "status": "known"},
    "destination_airports": ["BKK"],
    "departure_airport": "TLV",
    "travelers": {"adults": 2, "children": 0},
    "dates": {"departure": "2026-11-21", "return": "2026-12-05", "needs_confirmation": False, "candidate_ranges": []},
    "requested_services": ["flights"],
    "service_decisions": {
        "flights": {"wanted": True}, "lodging": {"wanted": False},
        "car": {"wanted": False}, "trip_planning": {"wanted": False},
    },
    "session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
    "active_session": None,
    "next_session": None,
    "ready_for_summary": True,
    "budget_per_person": {"amount": 1500, "currency": "EUR"},
    "flight": {"connection_preference": "אין העדפה", "baggage": ["carry_on_only"]},
    # Run-11 (22.10): ready_for_summary/the missing-summary safety net now
    # also requires accessibility genuinely resolved (see _guided_
    # incomplete_fields) - already true in this fixture, just not
    # previously represented, since this file predates that gate and tests
    # an orthogonal mechanism (the post-summary/missing-summary retry).
    "accessibility": {"needed": False},
    "guided": {"current_question": None, "attempts": 0, "answered": ["dates", "travelers", "accessibility", "baggage"]},
}

_OLD_SUMMARY_TEXT = (
    "סיכום החופשה: בנגקוק, 21.11.2026 - 05.12.2026, 2 מבוגרים. "
    "אם כל הפרטים נכונים, כתבי מאשרת."
)


# =====================================================================
# Bangkok-shape: relative shift request after the final summary.
# =====================================================================
def _post_claude_shift_post_summary(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
            "relative_date_hint": {
                "weekday_start": None, "weekday_end": None, "month_name": None,
                "month_relative": None, "part_of_month": None, "duration_days": None,
                "shift_days": 1,
            },
            "relative_date_hint_evidence": message_,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "בטח, 22.11.2026 עד 06.12.2026 - מתאים?"
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_post_claude_shift_post_summary):
    r_shift = client.post("/api/ariella/chat-clean", json={
        "message": "רגע, אפשר לדחות את כל הטיסה ביום אחד?",
        "history": [{"role": "assistant", "content": _OLD_SUMMARY_TEXT}],
        "trip_state": _ALL_DECIDED_STATE,
    })
data_shift = r_shift.get_json() or {}
dates_shift = (data_shift.get("trip_update") or {}).get("dates") or {}
reply_shift = str(data_shift.get("reply") or "")
check("Bangkok-shape: a post-summary shift request proposes exactly one "
      "pending candidate (22.11-06.12), departure/return untouched until "
      "confirmed - the pre-existing shift mechanism itself is unaffected",
      dates_shift.get("needs_confirmation") is True
      and dates_shift.get("departure") == "2026-11-21"
      and dates_shift.get("return") == "2026-12-05"
      and len(dates_shift.get("candidate_ranges") or []) == 1
      and "22.11.2026" in dates_shift["candidate_ranges"][0])
check("Bangkok-shape FIX: Tinkerbell's own proposal reply reaches the "
      "customer unmolested - NOT replaced by the stale old-dates summary "
      "(the live bug: reply was 'סיכום החופשה: ... 21.11.2026 - 05.12.2026')",
      reply_shift == "בטח, 22.11.2026 עד 06.12.2026 - מתאים?"
      and "סיכום החופשה" not in reply_shift
      and "21.11.2026" not in reply_shift)


# Second turn: the customer confirms the pending shift with a plain "כן" -
# this must actually commit the shifted dates (reusing the existing
# _accept_single_proposed_date_range mechanism, exactly as it already does
# mid-conversation) and the acknowledgement must also reach the customer
# unmolested.
def _post_claude_confirm_post_summary(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
            "relative_date_hint": {
                "weekday_start": None, "weekday_end": None, "month_name": None,
                "month_relative": None, "part_of_month": None, "duration_days": None, "shift_days": None,
            },
            "relative_date_hint_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "מעולה, עדכנתי ל-22.11.2026 עד 06.12.2026."
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_post_claude_confirm_post_summary):
    r_shift_confirm = client.post("/api/ariella/chat-clean", json={
        "message": "כן",
        "history": [
            {"role": "assistant", "content": _OLD_SUMMARY_TEXT},
            {"role": "user", "content": "רגע, אפשר לדחות את כל הטיסה ביום אחד?"},
            {"role": "assistant", "content": "בטח, 22.11.2026 עד 06.12.2026 - מתאים?"},
        ],
        "trip_state": dict(_ALL_DECIDED_STATE, dates=dates_shift),
    })
data_shift_confirm = r_shift_confirm.get_json() or {}
dates_shift_confirm = (data_shift_confirm.get("trip_update") or {}).get("dates") or {}
reply_shift_confirm = str(data_shift_confirm.get("reply") or "")
check("Bangkok-shape: confirming the pending shift with 'כן' actually "
      "commits the shifted dates (2026-11-21 -> 2026-11-22, "
      "2026-12-05 -> 2026-12-06) - the live bug left them at 21.11-05.12",
      dates_shift_confirm.get("departure") == "2026-11-22"
      and dates_shift_confirm.get("return") == "2026-12-06")
check("Bangkok-shape: after confirming, needs_confirmation is False and "
      "candidate_ranges is cleared",
      dates_shift_confirm.get("needs_confirmation") is False
      and dates_shift_confirm.get("candidate_ranges") == [])
check("Bangkok-shape FIX: the confirmation reply also reaches the "
      "customer unmolested, not the stale old-dates summary",
      reply_shift_confirm == "מעולה, עדכנתי ל-22.11.2026 עד 06.12.2026."
      and "סיכום החופשה" not in reply_shift_confirm)


# =====================================================================
# Batumi-shape: explicit new dates after the final summary, with a
# verified dates_evidence quote - commits immediately, no confirmation
# step (mirrors Corfu/U5's own already-passing behavior).
# =====================================================================
_BATUMI_STATE = dict(
    _ALL_DECIDED_STATE,
    destination={"places": ["בטומי"], "mode": "specific", "status": "known"},
    destination_airports=["BUS"],
    dates={"departure": "2027-06-04", "return": "2027-06-08", "needs_confirmation": False, "candidate_ranges": []},
)
_BATUMI_OLD_SUMMARY = (
    "סיכום החופשה: בטומי, 04.06.2027 - 08.06.2027, 2 מבוגרים. "
    "אם כל הפרטים נכונים, כתבי מאשרת."
)
_BATUMI_MESSAGE = "רגע, אפשר לצאת ב-5.6 ולחזור ב-9.6 במקום?"


def _post_claude_explicit_post_summary(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {"dates": {"departure": "2027-06-05", "return": "2027-06-09"}},
            "restart_request": False, "restart_evidence": None,
            "dates_evidence": "לצאת ב-5.6 ולחזור ב-9.6",
            "destination_evidence": None, "trip_type_evidence": None,
            "relative_date_hint": {
                "weekday_start": None, "weekday_end": None, "month_name": None,
                "month_relative": None, "part_of_month": None, "duration_days": None, "shift_days": None,
            },
            "relative_date_hint_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "מעולה, עדכנתי את התאריכים ל-05.06.2027 עד 09.06.2027."
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_post_claude_explicit_post_summary):
    r_batumi = client.post("/api/ariella/chat-clean", json={
        "message": _BATUMI_MESSAGE,
        "history": [{"role": "assistant", "content": _BATUMI_OLD_SUMMARY}],
        "trip_state": _BATUMI_STATE,
    })
data_batumi = r_batumi.get_json() or {}
dates_batumi = (data_batumi.get("trip_update") or {}).get("dates") or {}
reply_batumi = str(data_batumi.get("reply") or "")
check("Batumi-shape: explicit new dates with verified evidence commit "
      "IMMEDIATELY post-summary, no confirmation step (2027-06-05/09) - "
      "the live bug left state at 04-08.06",
      dates_batumi.get("departure") == "2027-06-05"
      and dates_batumi.get("return") == "2027-06-09")
check("Batumi-shape FIX: the acknowledgement reply reaches the customer "
      "unmolested, not the stale old-dates summary",
      reply_batumi == "מעולה, עדכנתי את התאריכים ל-05.06.2027 עד 09.06.2027."
      and "סיכום החופשה" not in reply_batumi
      and "04.06.2027" not in reply_batumi)


# =====================================================================
# Regression: the pre-existing "opposite failure" safety net (Shaked,
# Haifa->Bangkok) must still fire the FIRST time every domain becomes
# decided - a genuinely NEW state this turn, with the final summary never
# shown before in this conversation (no "מאשר"/"חופשה נעימה" anywhere in
# history, and no final_summary_shown flag) - unlike every post-summary
# scenario above, where the summary was already shown earlier.
# =====================================================================
_FIRST_TIME_DECIDED_STATE = dict(_ALL_DECIDED_STATE)
_FIRST_TIME_DECIDED_STATE.pop("final_summary_shown", None)


def _post_claude_unrelated_post_summary(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
            "relative_date_hint": {
                "weekday_start": None, "weekday_end": None, "month_name": None,
                "month_relative": None, "part_of_month": None, "duration_days": None, "shift_days": None,
            },
            "relative_date_hint_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        # Deliberately never produces מאשר/חופשה נעימה, even on the forced
        # retry (same mock is reused for both calls) - the exact failure
        # mode this safety net exists to catch.
        return "בשמחה! יש עוד משהו שאפשר לעזור בו?"
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_post_claude_unrelated_post_summary):
    r_unrelated = client.post("/api/ariella/chat-clean", json={
        "message": "מעולה, זה הכל",
        # No prior assistant message ever contained the approval phrase -
        # the summary genuinely hasn't been shown yet in this conversation.
        "history": [{"role": "assistant", "content": "מעולה, פרטי הטיסה מלאים."}],
        "trip_state": _FIRST_TIME_DECIDED_STATE,
    })
data_unrelated = r_unrelated.get_json() or {}
reply_unrelated = str(data_unrelated.get("reply") or "")
check("regression: the missing-final-summary safety net still fires the "
      "FIRST time every domain becomes decided, with the summary never "
      "shown before in this conversation (Shaked's original Haifa->"
      "Bangkok case) - a reply that genuinely fails to produce it is "
      "still replaced",
      any(p in reply_unrelated for p in ("מאשר", "חופשה נעימה")))

# =====================================================================
# Rework (א): confirms the simplified final_summary_shown mechanism (see
# below) also covers budget/baggage/traveler-count changes post-summary,
# not just dates - once the summary has genuinely been shown once, EVERY
# later reply passes through regardless of which fact the current turn
# touches, so these scenarios are no longer field-specific special cases.
# =====================================================================
def _post_claude_budget_change_post_summary(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {"budget_per_person": {"amount": 4000, "currency": "ILS"}},
            "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
            "relative_date_hint": {
                "weekday_start": None, "weekday_end": None, "month_name": None,
                "month_relative": None, "part_of_month": None, "duration_days": None, "shift_days": None,
            },
            "relative_date_hint_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "רק לוודא - 4000 ש\"ח לאדם, נכון?"
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_post_claude_budget_change_post_summary):
    r_budget = client.post("/api/ariella/chat-clean", json={
        "message": "רגע, אפשר להעלות את התקציב ל-4000 שקל לאדם?",
        "history": [{"role": "assistant", "content": _OLD_SUMMARY_TEXT}],
        "trip_state": _ALL_DECIDED_STATE,
    })
data_budget = r_budget.get_json() or {}
budget_out = (data_budget.get("trip_update") or {}).get("budget_per_person") or {}
reply_budget = str(data_budget.get("reply") or "")
check("rework (א): a post-summary budget change updates state",
      budget_out.get("amount") == 4000 and budget_out.get("currency") == "ILS")
check("rework (א) FIX: the reply reaches the customer unmolested even "
      "though it never says 'מאשר' - budget is a generalized fact, not "
      "just dates",
      reply_budget == 'רק לוודא - 4000 ש"ח לאדם, נכון?'
      and "סיכום החופשה" not in reply_budget)

# Regression: the FIRST turn that sets a previously-unknown budget (the
# genuine path to the first real summary) must never be treated as a
# post-summary correction - only an ALREADY-resolved budget counts.
_NO_BUDGET_YET_STATE = dict(_ALL_DECIDED_STATE, budget_per_person={})
with patch.object(chat, "_post_claude", side_effect=_post_claude_budget_change_post_summary):
    r_first_budget = client.post("/api/ariella/chat-clean", json={
        "message": "4000 שקל לאדם",
        "history": [{"role": "assistant", "content": "מה התקציב שלכם לאדם לטיסה?"}],
        "trip_state": _NO_BUDGET_YET_STATE,
    })
data_first_budget = r_first_budget.get_json() or {}
reply_first_budget = str(data_first_budget.get("reply") or "")
check("regression (א): a budget stated for the FIRST time (never "
      "resolved before this turn) does NOT bypass the safety net - the "
      "mocked reply here lacks 'מאשר', so it must still be replaced",
      reply_first_budget != 'רק לוודא - 4000 ש"ח לאדם, נכון?')


def _post_claude_travelers_change_post_summary(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {"travelers": {"adults": 3, "children": 0}},
            "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
            "relative_date_hint": {
                "weekday_start": None, "weekday_end": None, "month_name": None,
                "month_relative": None, "part_of_month": None, "duration_days": None, "shift_days": None,
            },
            "relative_date_hint_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "קלטתי, 3 מבוגרים במקום 2."
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_post_claude_travelers_change_post_summary):
    r_travelers = client.post("/api/ariella/chat-clean", json={
        "message": "עוד רגע, בעצם נוסעים 3 מבוגרים לא 2",
        "history": [{"role": "assistant", "content": _OLD_SUMMARY_TEXT}],
        "trip_state": _ALL_DECIDED_STATE,
    })
data_travelers = r_travelers.get_json() or {}
travelers_out = (data_travelers.get("trip_update") or {}).get("travelers") or {}
reply_travelers = str(data_travelers.get("reply") or "")
check("rework (א): a post-summary traveler-count change updates state",
      travelers_out.get("adults") == 3)
check("rework (א) FIX: the reply reaches the customer unmolested",
      reply_travelers == "קלטתי, 3 מבוגרים במקום 2."
      and "סיכום החופשה" not in reply_travelers)


def _post_claude_baggage_change_post_summary(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    # Confirmed by direct repro: once every domain is decided, _handle_
    # guided_extraction_turn is skipped entirely (gated on _all_domains_
    # already_decided), and _baggage_answer_by_meaning/_deterministic_
    # baggage_facts only ever fire while baggage is still UNKNOWN - a
    # post-summary baggage CORRECTION flows through the general extractor's
    # own trip_update.flight.baggage field instead (merged at the very top
    # of the per-turn pipeline), same as any other already-known fact.
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {"flight": {"baggage": ["checked_bag"]}},
            "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
            "relative_date_hint": {
                "weekday_start": None, "weekday_end": None, "month_name": None,
                "month_relative": None, "part_of_month": None, "duration_days": None, "shift_days": None,
            },
            "relative_date_hint_evidence": None,
            # Dry-run 5b sticky-baggage guard (_guard_baggage_change_evidence):
            # a claimed flight.baggage change now requires a genuine
            # baggage_evidence quote from the current message - supplied here
            # since the message itself ("...נרצה גם מזוודה בבטן המטוס")
            # genuinely names the new baggage type.
            "baggage_evidence": "מזוודה בבטן המטוס",
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "בטח, עדכנתי - מזוודה בבטן המטוס במקום רק תיק יד."
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_post_claude_baggage_change_post_summary):
    r_baggage = client.post("/api/ariella/chat-clean", json={
        "message": "רגע, בעצם נרצה גם מזוודה בבטן המטוס",
        "history": [{"role": "assistant", "content": _OLD_SUMMARY_TEXT}],
        "trip_state": _ALL_DECIDED_STATE,
    })
data_baggage = r_baggage.get_json() or {}
baggage_out = ((data_baggage.get("trip_update") or {}).get("flight") or {}).get("baggage")
reply_baggage = str(data_baggage.get("reply") or "")
check("rework (א): a post-summary baggage change updates state",
      baggage_out == ["checked_bag"])
check("rework (א) FIX: the reply reaches the customer unmolested",
      reply_baggage == "בטח, עדכנתי - מזוודה בבטן המטוס במקום רק תיק יד."
      and "סיכום החופשה" not in reply_baggage)


# =====================================================================
# Second rejection (Shaked, 21.10.2026, on dfe869d): the before/after
# STATE comparison still missed the case where a genuine post-summary
# request produces a CLARIFYING question with nothing written to state
# yet - no fact changed this turn, so the old gate stayed closed and the
# clarifying question itself got stomped. The three exact live examples
# Shlomo relayed, reproduced here end-to-end: a vague ask with no number/
# detail yet, where Tinkerbell correctly asks for it instead of guessing.
# =====================================================================
def _post_claude_clarifying_question_post_summary(reply_text):
    def _fake(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
        if source == "state_extractor":
            return "{}"  # Nothing to write yet - the request is still vague.
        if source == "guided_extract":
            return json.dumps({"status": "other_topic", "field": None, "evidence": None})
        if source == "tinkerbell_reply":
            return reply_text
        return "{}"
    return _fake


for _label, _message, _clarifying_reply in (
    ("vague budget increase", "אפשר להעלות קצת את התקציב?", "לכמה תרצי להעלות?"),
    ("vague traveler addition", "אולי מצטרפת עוד חברה", "אז תהיו 4 נוסעות?"),
    ("vague postpone request", "אפשר לדחות קצת?", "בכמה ימים תרצי לדחות?"),
):
    with patch.object(chat, "_post_claude", side_effect=_post_claude_clarifying_question_post_summary(_clarifying_reply)):
        _r_clarify = client.post("/api/ariella/chat-clean", json={
            "message": _message,
            "history": [{"role": "assistant", "content": _OLD_SUMMARY_TEXT}],
            "trip_state": _ALL_DECIDED_STATE,
        })
    _data_clarify = _r_clarify.get_json() or {}
    _reply_clarify = str(_data_clarify.get("reply") or "")
    check(f"second-rejection FIX: a clarifying question with nothing yet "
          f"written to state ({_label}) reaches the customer unmolested, "
          f"not the stale old summary",
          _reply_clarify == _clarifying_reply and "סיכום החופשה" not in _reply_clarify)


# =====================================================================
# Rework (ב): the extractor gets explicit situational grounding once
# every domain is decided and dates are closed.
# =====================================================================
check("direct: _post_summary_dates_context_hint is empty when not every "
      "domain is decided yet",
      chat._post_summary_dates_context_hint({
          "session_status": {"flights": "active", "lodging": "pending", "car": "pending", "trip_planning": "pending"},
          "dates": {"departure": "2026-11-21", "return": "2026-12-05"},
      }) == "")
check("direct: empty when dates were never actually closed",
      chat._post_summary_dates_context_hint({
          "session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
          "dates": {"departure": None, "return": None},
      }) == "")
_post_summary_hint = chat._post_summary_dates_context_hint({
    "session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
    "dates": {"departure": "2026-11-21", "return": "2026-12-05"},
})
check("direct: once every domain is decided and dates are closed, the "
      "hint names the exact current dates and instructs treating a "
      "further date mention as a real change request",
      "21.11.2026" in _post_summary_hint and "5.12.2026" in _post_summary_hint
      and "בקשת שינוי תקפה" in _post_summary_hint)
check("direct: no verb list of any kind in the hint (Shlomo's explicit "
      "21.10 instruction, PR #117's own rework) - only the one word "
      "'אחר' for 'a different date', never an enumeration",
      "לזוז" not in _post_summary_hint and "לדחות" not in _post_summary_hint
      and "להקדים" not in _post_summary_hint)


# End-to-end: the hint text actually reaches the extractor's own system_
# dynamic once every domain is decided and dates are closed.
_captured_system_dynamic = []


def _post_claude_capture_system_dynamic(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        _captured_system_dynamic.append(system_dynamic)
        return "{}"
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "בשמחה."
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_post_claude_capture_system_dynamic):
    client.post("/api/ariella/chat-clean", json={
        "message": "אפשר לטוס ביום אחר?",
        "history": [{"role": "assistant", "content": _OLD_SUMMARY_TEXT}],
        "trip_state": _ALL_DECIDED_STATE,
    })
check("end-to-end: the post-summary dates context hint is actually woven "
      "into the extractor's system_dynamic for a post-summary turn",
      _captured_system_dynamic and "בקשת שינוי תקפה" in _captured_system_dynamic[-1])


# Per Shlomo's relay of the business owner's diagnostics.csv review
# (dates_change, 21.10.2026): the live failures in run-7 (members 310-315)
# and run-6 Paphos (member 303) show present=false/verified=null almost
# every turn - the EXTRACTOR never returned differing dates/dates_
# evidence at all post-summary, confirming (ב) is the right direction.
# Shlomo's explicit ask: confirm the hint fires on exactly these turns -
# the two live phrasings themselves, word for word.
for _label, _message in (
    ("Bangkok's exact live phrasing ('לדחות... ביום אחד')", "רגע, אפשר לדחות את כל הטיסה ביום אחד?"),
    ("Batumi's exact live phrasing (explicit new dates)", "רגע, אפשר לצאת ב-5.6 ולחזור ב-9.6 במקום?"),
):
    _captured_system_dynamic.clear()
    with patch.object(chat, "_post_claude", side_effect=_post_claude_capture_system_dynamic):
        client.post("/api/ariella/chat-clean", json={
            "message": _message,
            "history": [{"role": "assistant", "content": _OLD_SUMMARY_TEXT}],
            "trip_state": _ALL_DECIDED_STATE,
        })
    check(f"end-to-end: the context hint fires on {_label}",
          _captured_system_dynamic and "בקשת שינוי תקפה" in _captured_system_dynamic[-1])


# =====================================================================
# Rework (ג): a bare "כן" must never silently pick one of several
# pending date candidates.
# =====================================================================
_tinkerbell_system_src = chat.TINKERBELL_SYSTEM if isinstance(chat.TINKERBELL_SYSTEM, str) else ""
check("rework (ג): TINKERBELL_SYSTEM forbids bundling a general yes/no "
      "confirm with presenting candidate_ranges in the same message",
      "לבדו לא יכול לבחור בין כמה אפשרויות" in _tinkerbell_system_src)

# inspect.getsource returns the literal SOURCE TEXT, not the evaluated
# (concatenated) prompt string - adjacent string literals that wrap across
# source lines show up with the raw "\n            \"" of the next line
# still in between them, so a substring spanning such a wrap silently
# fails. Capture the actual rendered prompt the model receives instead.
_captured_dates_prompt = []


def _post_claude_capture_dates_prompt(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "guided_extract":
        _captured_dates_prompt.append(system_static)
        return json.dumps({
            "status": "answered", "departure": None, "return": None, "nights": None,
            "period": None, "flexibility_days": None, "confidence": "low",
            "also_mentioned": None, "correction": None,
        })
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_post_claude_capture_dates_prompt):
    chat._guided_extract_answer(
        "test-key", "claude-sonnet-5", "dates", "כן", [],
        {"dates": {"candidate_ranges": ["a", "b"]}, "travelers": {}},
    )
_dates_guided_extract_prompt = _captured_dates_prompt[0] if _captured_dates_prompt else ""
check("rework (ג): the guided_extract dates prompt forbids guessing which "
      "pending candidate a bare agreement selects",
      "אסור" in _dates_guided_extract_prompt and "לנחש איזו מהן נבחרה" in _dates_guided_extract_prompt)


# End-to-end: a correctly-behaving model (per the new instruction) returns
# confidence:"low" for a bare "כן" against two pending candidates - the
# code must not commit any candidate, must not crash, and must leave the
# choice genuinely still open.
_MULTI_CANDIDATE_STATE = dict(
    _ALL_DECIDED_STATE,
    session_status={"flights": "active", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
    active_session="flights",
    dates={
        "departure": None, "return": None, "needs_confirmation": True,
        "candidate_ranges": ["יום שישי 20.11.2026–יום שישי 27.11.2026", "יום שבת 28.11.2026–יום שבת 05.12.2026"],
    },
    guided={"current_question": "dates", "attempts": 0, "answered": ["travelers"]},
)


def _post_claude_ambiguous_yes_multi_candidate(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return "{}"
    if source == "guided_extract":
        return json.dumps({
            "status": "answered", "departure": None, "return": None, "nights": None,
            "period": None, "flexibility_days": None, "confidence": "low",
            "also_mentioned": None, "correction": None,
        })
    if source == "tinkerbell_reply":
        return "איזו משתי האפשרויות מתאימה לך יותר?"
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_post_claude_ambiguous_yes_multi_candidate):
    r_ambiguous = client.post("/api/ariella/chat-clean", json={
        "message": "כן",
        "history": [{"role": "assistant", "content": "סוף נובמבר, נכון? יום שישי 20.11.2026–יום שישי 27.11.2026 או יום שבת 28.11.2026–יום שבת 05.12.2026."}],
        "trip_state": _MULTI_CANDIDATE_STATE,
    })
data_ambiguous = r_ambiguous.get_json() or {}
dates_ambiguous = (data_ambiguous.get("trip_update") or {}).get("dates") or {}
check("rework (ג): a correctly low-confidence model response to a bare "
      "'כן' against two candidates never commits either one",
      dates_ambiguous.get("departure") is None and dates_ambiguous.get("return") is None)
check("rework (ג): both candidates are still on the table - the choice "
      "genuinely stays open, never silently narrowed to the first",
      len(dates_ambiguous.get("candidate_ranges") or []) == 2)

if FAILED:
    print(f"\n{len(FAILED)} CHECK(S) FAILED:")
    for name in FAILED:
        print(f"  - {name}")
    sys.exit(1)
print(f"\nALL {('POST-SUMMARY-DATE-CHANGE')} TESTS PASSED")
