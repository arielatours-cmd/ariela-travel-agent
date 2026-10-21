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
# Haifa->Bangkok) must still fire when a reply genuinely fails to produce
# the final summary and dates are NOT part of what changed this turn.
# =====================================================================
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
        "message": "תודה רבה!",
        "history": [{"role": "assistant", "content": _OLD_SUMMARY_TEXT}],
        "trip_state": _ALL_DECIDED_STATE,
    })
data_unrelated = r_unrelated.get_json() or {}
dates_unrelated = (data_unrelated.get("trip_update") or {}).get("dates") or {}
reply_unrelated = str(data_unrelated.get("reply") or "")
check("regression: dates genuinely unchanged this turn (not part of the "
      "new gate) - _post_summary_date_change_pending must not fire",
      dates_unrelated.get("departure") == "2026-11-21"
      and dates_unrelated.get("return") == "2026-12-05")
check("regression: the missing-final-summary safety net still replaces a "
      "reply that genuinely fails to produce the final summary when no "
      "date change is in flight (Shaked's original Haifa->Bangkok case)",
      any(p in reply_unrelated for p in ("מאשר", "חופשה נעימה")))

if FAILED:
    print(f"\n{len(FAILED)} CHECK(S) FAILED:")
    for name in FAILED:
        print(f"  - {name}")
    sys.exit(1)
print(f"\nALL {('POST-SUMMARY-DATE-CHANGE')} TESTS PASSED")
