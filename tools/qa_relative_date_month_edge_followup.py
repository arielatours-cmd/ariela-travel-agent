"""QA for two non-blocking notes Shlomo relayed (20.10.2026) when merging
PR #101 (relative-date help, a905dd4), for the next PR on this topic:

"שתי הערות לא חוסמות, ל-PR הבא:
(א) ב'סוף החודש', עדיף לבחור תאריך יציאה כך שגם החזרה תיפול בתוך החודש.
האפשרות השנייה כרגע, 30.11–7.12, נופלת ברובה בדצמבר.
(ב) כשיש רק אפשרות אחת בחלון, למשל 'תחילת החודש הבא, חמישי עד ראשון',
הצע גם את השבוע הבא אחריה כאפשרות שנייה."

Both fixes are in _candidate_dates_from_relative_hint:

(a) duration-only branch (no weekday pair, e.g. "סוף החודש הבא, שבוע"):
    now prefers a departure within the window whose RETURN also stays in
    the same requested month, falling back to a month-spilling day only
    when no same-month-return day exists in the window at all (the trip
    is simply too long to fit).

(b) weekday-pair branch: when the narrow ~10-day window contains only ONE
    occurrence of the requested weekday pair, the following week's
    occurrence of the same pair is offered as a second option instead of
    leaving the customer with a single bare candidate.

Also covers bug #4 from the SAME live run's stage-1 run-2 report
(relayed together with these two notes, combined into this PR per
Shlomo's own instruction): _deterministic_period_facts's "אחרי ה-X"
branch (a weekday pair plus an explicit anchor day, e.g. "ראשון עד חמישי
אחרי ה-15 ביוני") used to return a single resolved departure/return
directly, with no needs_confirmation key at all - _merge_trip_state then
treated that as an unconditionally-settled fact, silently closing dates
with zero confirmation step. A relative date must always require
explicit confirmation, even with only one computed option (the sibling
weekday-pair-with-part branch right above it already did this
correctly) - this branch is now shaped the same way.

Run: python3 tools/qa_relative_date_month_edge_followup.py
"""
import os
import sys
import sqlite3
from datetime import date, timedelta, datetime, timezone
from unittest.mock import patch
import json
import re

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


def _dates_in_label(label):
    return [date(int(y), int(m), int(d)) for d, m, y in re.findall(r"(\d{2})\.(\d{2})\.(\d{4})", label)]


# =====================================================================
# (a) "סוף החודש הבא, שבוע" (end of next month, a week) - both candidates'
# RETURN should stay within the requested month when a same-month-return
# day exists in the window at all (a 30-day month's last ~10 days easily
# fit a 7-day trip with room to spare).
# =====================================================================
r = chat._candidate_dates_from_relative_hint(
    {"month_relative": "next", "part_of_month": "end", "duration_days": 7}
)
labels = r["dates"]["candidate_ranges"]
check("'סוף החודש הבא, שבוע' produces 2 candidates",
      len(labels) == 2)
_same_month_ok = []
for lbl in labels:
    dep, ret = _dates_in_label(lbl)
    _same_month_ok.append(dep.month == ret.month and dep.year == ret.year)
check("every candidate's RETURN stays within the same month as its "
      f"DEPARTURE (no more 30.11–07.12-style spillover) - got {labels}",
      all(_same_month_ok))

# Regression: a duration genuinely too long to fit in the window at all
# must still fall back to a month-spilling day rather than returning
# nothing - same-month-return is a preference, never a hard requirement.
r_long = chat._candidate_dates_from_relative_hint(
    {"month_relative": "next", "part_of_month": "end", "duration_days": 25}
)
check("a duration too long to keep the return in-month still produces "
      "real candidates (falls back to a spilling day rather than {})",
      bool(r_long.get("dates", {}).get("candidate_ranges")))

# =====================================================================
# (b) "תחילת החודש הבא, חמישי עד ראשון" (start of next month, Thu-Sun) -
# the narrow start-of-month window often holds only one Thursday, which
# used to leave a single bare candidate.
# =====================================================================
r2 = chat._candidate_dates_from_relative_hint(
    {"weekday_start": "חמישי", "weekday_end": "ראשון", "month_relative": "next", "part_of_month": "start"}
)
labels2 = r2["dates"]["candidate_ranges"]
check("'תחילת החודש הבא, חמישי עד ראשון' produces 2 candidates even when "
      f"the window holds only one real occurrence - got {labels2}",
      len(labels2) == 2)
_dep1, _ret1 = _dates_in_label(labels2[0])
_dep2, _ret2 = _dates_in_label(labels2[1])
check("when a second candidate had to be manufactured, it is exactly one "
      "week after the first (same weekday pair, same duration)",
      (_dep2 - _dep1).days == 7 and (_ret2 - _ret1).days == 7)
check("both candidates still use the customer's own weekday words "
      "(חמישי/ראשון)",
      all("יום חמישי" in c and "יום ראשון" in c for c in labels2))

# Regression: a window that already yields 2+ real occurrences on its own
# must not have a manufactured one appended on top (never 3 candidates).
r3 = chat._candidate_dates_from_relative_hint(
    {"weekday_start": "ראשון", "weekday_end": "חמישי", "month_name": "יוני", "part_of_month": "end"}
)
check("a window with 2 genuine occurrences on its own still returns "
      "exactly 2 candidates (no manufactured third one)",
      len(r3["dates"]["candidate_ranges"]) == 2)

# =====================================================================
# Bug #4 (same live run, combined into this PR per Shlomo's instruction):
# _deterministic_period_facts's "אחרי ה-X" branch (weekday pair + an
# explicit anchor day) used to return a single resolved departure/return
# directly with NO needs_confirmation key at all - _merge_trip_state then
# treated that as an unconditionally-settled fact, silently closing
# dates with zero confirmation step.
# =====================================================================
r_after = chat._deterministic_period_facts("ראשון עד חמישי ביוני, אחרי ה-15", [])
check("'אחרי ה-X' resolution is a PENDING single candidate, never "
      "silently-settled departure/return",
      r_after["dates"]["departure"] is None
      and r_after["dates"]["return"] is None
      and r_after["dates"]["needs_confirmation"] is True
      and len(r_after["dates"]["candidate_ranges"]) == 1)

# Confirm this single candidate is actually accepted by the existing
# candidate-choice/single-proposal mechanisms once the customer agrees -
# the fix must not create a candidate nothing can ever resolve.
_state_with_after_candidate = {"dates": {
    "departure": None, "return": None, "needs_confirmation": True,
    "candidate_ranges": r_after["dates"]["candidate_ranges"],
}}
accepted = chat._accept_single_proposed_date_range("כן", _state_with_after_candidate)
check("a plain 'כן' against the single 'אחרי ה-X' candidate commits real "
      "ISO dates with needs_confirmation=False",
      bool(accepted.get("dates", {}).get("departure"))
      and accepted["dates"]["needs_confirmation"] is False)

# =====================================================================
# Shaked's direct report (live stage-1 run-2, Rome, NEW exact transcript
# distinct from the "אחרי ה-X" case above): "בתחילת החודש הבא, מחמישי עד
# ראשון" was saved IMMEDIATELY with no confirmation at all, and Ariella's
# own first reply claimed "כבר יש לי את התאריכים" as if already settled.
# _candidate_dates_from_relative_hint itself was verified (directly) to
# already compute the correct pending single candidate - the real bug is
# that EXTRACTOR_SYSTEM already forbids the model from also writing
# dates.departure/return directly once relative_date_hint fires, but the
# model isn't always compliant. When it writes both on the same turn,
# _merge_trip_state's own "exact dates replace" branch locks in that
# direct (uncomputed) write as already-confirmed before the relative-
# hint code ever runs, and its anti-regression guard then refuses to
# flip needs_confirmation back to True - this end-to-end test simulates
# exactly that non-compliant extractor output through the real endpoint.
# =====================================================================
def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports,gender) "
            "VALUES(?,?,?,?,?,?,?,?)",
            ("QA Relative Date Extractor Bypass", email, generate_password_hash("Test1234!"),
             datetime.now(timezone.utc).isoformat(), "active", 0, "[]", "female"),
        )
        return cur.lastrowid


member = _make_member("qa-relative-date-extractor-bypass@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member

_ROME_MESSAGE = "בתחילת החודש הבא, מחמישי עד ראשון"


def _post_claude_noncompliant_direct_write(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        # The model correctly fires relative_date_hint AND (non-compliantly,
        # despite the prompt's own explicit prohibition) ALSO writes exact
        # dates.departure/return directly in trip_update this same turn.
        return json.dumps({
            "trip_update": {"dates": {"departure": "2026-11-05", "return": "2026-11-08"}},
            "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
            "relative_date_hint": {
                "weekday_start": "חמישי", "weekday_end": "ראשון",
                "month_name": None, "month_relative": "next",
                "part_of_month": "start", "duration_days": None, "shift_days": None,
            },
            "relative_date_hint_evidence": message_,
            "link_request": False, "link_request_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "מצוין, הנה האפשרות ליציאה - מתאים לך?"
    return "{}"


rome_base_state = {
    "trip_type": "standard",
    "destination": {"places": ["רומא"], "mode": "specific", "status": "known"},
    "destination_airports": ["FCO"],
    "departure_airport": "TLV",
    "travelers": {"adults": 2, "children": 0},
    "dates": {"departure": None, "return": None},
    "requested_services": ["flights"],
    "service_decisions": {"flights": {"wanted": True}},
    "session_status": {"flights": "active", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
    "active_session": "flights",
}

with patch.object(chat, "_post_claude", side_effect=_post_claude_noncompliant_direct_write):
    r_rome = client.post("/api/ariella/chat-clean", json={
        "message": _ROME_MESSAGE,
        "history": [{"role": "assistant", "content": "מתי תרצו לטוס?"}],
        "trip_state": rome_base_state,
    })
data_rome = r_rome.get_json() or {}
dates_rome = (data_rome.get("trip_update") or {}).get("dates") or {}
check("end-to-end (Rome, non-compliant extractor also writing dates "
      "directly): departure/return are NOT silently settled to the "
      f"model's own direct (uncomputed) write - got {dates_rome}",
      dates_rome.get("departure") is None and dates_rome.get("return") is None)
check("end-to-end: needs_confirmation=True and a real pending candidate "
      "is offered instead, computed by _candidate_dates_from_relative_hint",
      dates_rome.get("needs_confirmation") is True
      and bool(dates_rome.get("candidate_ranges")))

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL RELATIVE-DATE-MONTH-EDGE-FOLLOWUP TESTS PASSED")
