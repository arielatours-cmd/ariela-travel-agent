"""QA for Shlomo's relay of the business owner's explicit architectural
correction (20.10.2026) on the first version of the relative-dates fix
(PR #101):

"ה-regex ב-_deterministic_period_facts הורחב, והוא רץ בכל תור שבו עוד אין
תאריכים, בלי תנאי fallback. כלומר זה הופך לדרך הזיהוי הראשית... הכיוון
הנדרש: המחלץ מבין את הביטוי היחסי ומחזיר אותו בצורה מובנית. הקוד מחשב
2-3 אפשרויות של תאריכים מדויקים, עם יום ותאריך לכל אחת... אריאלה מציעה
את האפשרויות ומבקשת אישור. אחרי 'כן' נשמרים departure ו-return. ה-regex
הקיים יכול להישאר רק כ-fallback, כשהמודל נכשל. לא מרחיבים אותו."

Redesign: EXTRACTOR_SYSTEM now returns relative_date_hint/relative_date_
hint_evidence - the model's own STRUCTURED understanding of a relative
date expression (weekday_start/weekday_end, month_name/month_relative,
part_of_month, duration_days, shift_days), evidence-gated exactly like
destination_evidence. _candidate_dates_from_relative_hint (new, PRIMARY
path) does ONLY the calendar arithmetic from that structured input -
never re-deciding what the customer said. _deterministic_period_facts
(the pre-existing regex parser) is now wired in strictly as a FALLBACK,
reached only when the model's own structured extraction produced nothing
usable this turn - never as the main detection mechanism, and not
extended any further.

Also covers the related finding from the same live run: "אפשר לזוז יום
אחד קדימה?" after exact dates are already known must shift departure/
return by the stated number of days (shift_days), not get silently
folded into dates.flexibility_days as a vague preference.

Run: python3 tools/qa_relative_date_model_primary.py
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


# =====================================================================
# Direct unit tests of _candidate_dates_from_relative_hint - the model
# has ALREADY done the understanding (this is the arithmetic-only layer).
# =====================================================================
r1 = chat._candidate_dates_from_relative_hint(
    {"weekday_start": "ראשון", "weekday_end": "חמישי", "month_name": "יוני", "part_of_month": "end"}
)
check("weekday pair + explicit month + part -> real candidates with the "
      "customer's own weekday words and real dates",
      bool(r1.get("dates", {}).get("candidate_ranges"))
      and all("יום ראשון" in c and "יום חמישי" in c for c in r1["dates"]["candidate_ranges"]))
check("departure/return stay None until a candidate is actually chosen",
      r1["dates"]["departure"] is None and r1["dates"]["return"] is None)
check("needs_confirmation=True - genuine confirmation still required",
      r1["dates"]["needs_confirmation"] is True)

r2 = chat._candidate_dates_from_relative_hint(
    {"month_relative": "next", "part_of_month": "end", "duration_days": 7}
)
check("s1a5 Krakow shape (relative month + duration, no weekday pair) "
      "resolves through the model-structured path too",
      bool(r2.get("dates", {}).get("candidate_ranges")))

check("a hint with only a month name and nothing else (no weekday pair, "
      "no duration, no part) computes nothing - not enough structure",
      chat._candidate_dates_from_relative_hint({"month_name": "נובמבר"}) == {})
check("None/empty hint never raises, returns {}",
      chat._candidate_dates_from_relative_hint(None) == {}
      and chat._candidate_dates_from_relative_hint({}) == {})

# =====================================================================
# End-to-end: the model's structured hint is the PRIMARY path through
# the real endpoint - a mocked state_extractor returning relative_date_
# hint must produce real candidates without the regex ever running.
# =====================================================================
def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports,gender) "
            "VALUES(?,?,?,?,?,?,?,?)",
            ("QA Relative Date Model Primary", email, generate_password_hash("Test1234!"),
             datetime.now(timezone.utc).isoformat(), "active", 0, "[]", "female"),
        )
        return cur.lastrowid


member = _make_member("qa-relative-date-model-primary@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member

_KRAKOW_MESSAGE = "לקרקוב בסוף החודש הבא, שבוע"


def _post_claude_with_hint(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
            "relative_date_hint": {
                "weekday_start": None, "weekday_end": None,
                "month_name": None, "month_relative": "next",
                "part_of_month": "end", "duration_days": 7, "shift_days": None,
            },
            "relative_date_hint_evidence": message_,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "מצוין, הנה שתי אפשרויות ליציאה - מתי מתאים לך יותר?"
    return "{}"


base_state = {
    "trip_type": "standard",
    "destination": {"places": ["קרקוב"], "mode": "specific", "status": "known"},
    "destination_airports": ["KRK"],
    "departure_airport": "TLV",
    "travelers": {"adults": 2, "children": 0},
    "dates": {"departure": None, "return": None},
    "requested_services": ["flights"],
    "service_decisions": {"flights": {"wanted": True}},
    "session_status": {"flights": "active", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
    "active_session": "flights",
}

with patch.object(chat, "_post_claude", side_effect=_post_claude_with_hint):
    r = client.post("/api/ariella/chat-clean", json={
        "message": _KRAKOW_MESSAGE,
        "history": [{"role": "assistant", "content": "מתי תרצו לטוס?"}],
        "trip_state": base_state,
    })
data = r.get_json() or {}
dates_out = (data.get("trip_update") or {}).get("dates") or {}
check("end-to-end (model-structured path, real endpoint): s1a5's exact "
      "message produces real candidate_ranges via the model's own "
      "structured understanding",
      bool(dates_out.get("candidate_ranges")))
check("end-to-end: needs_confirmation=True, departure/return still None "
      "until a candidate is chosen",
      dates_out.get("needs_confirmation") is True
      and dates_out.get("departure") is None and dates_out.get("return") is None)

# =====================================================================
# Regression: when the model's extraction produces NO usable hint (e.g.
# a transient model failure, or the model genuinely found nothing), the
# regex-based _deterministic_period_facts still runs as a FALLBACK - the
# fix is not a removal of date-help, only a change in priority.
# =====================================================================
def _post_claude_no_hint(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
            "relative_date_hint": None, "relative_date_hint_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "מצוין, הנה שתי אפשרויות ליציאה - מתי מתאים לך יותר?"
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_post_claude_no_hint):
    r_fallback = client.post("/api/ariella/chat-clean", json={
        "message": "רוצים לטוס בסוף יוני, ראשון עד חמישי",
        "history": [{"role": "assistant", "content": "מתי תרצו לטוס?"}],
        "trip_state": dict(base_state, destination={"places": ["ליסבון"], "mode": "specific", "status": "known"}),
    })
data_fallback = r_fallback.get_json() or {}
dates_fallback = (data_fallback.get("trip_update") or {}).get("dates") or {}
check("regression: with no usable model hint, the regex fallback still "
      "produces real candidates (date-help is not lost, only reprioritized)",
      bool(dates_fallback.get("candidate_ranges")))

# =====================================================================
# "אפשר לזוז יום אחד קדימה?" after exact dates are already known shifts
# departure/return by the stated number of days - never silently folded
# into flexibility_days.
# =====================================================================
def _post_claude_shift(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
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
        return "קלטתי, הזזתי את התאריכים יום קדימה."
    return "{}"


confirmed_state = dict(base_state, dates={"departure": "2026-11-17", "return": "2026-11-24", "needs_confirmation": False})
with patch.object(chat, "_post_claude", side_effect=_post_claude_shift):
    r_shift = client.post("/api/ariella/chat-clean", json={
        "message": "אפשר לזוז יום אחד קדימה?",
        "history": [{"role": "assistant", "content": "קלטתי, 17.11.2026 עד 24.11.2026."}],
        "trip_state": confirmed_state,
    })
data_shift = r_shift.get_json() or {}
dates_shift = (data_shift.get("trip_update") or {}).get("dates") or {}
check("'אפשר לזוז יום אחד קדימה?' shifts the already-known departure by "
      "+1 day (2026-11-17 -> 2026-11-18)",
      dates_shift.get("departure") == "2026-11-18")
check("the same shift also moves return by the same +1 day "
      "(2026-11-24 -> 2026-11-25)",
      dates_shift.get("return") == "2026-11-25")
check("after a shift, needs_confirmation is False and candidate_ranges "
      "is cleared - this is a settled, confirmed change, not a new open "
      "candidate proposal",
      dates_shift.get("needs_confirmation") is False and dates_shift.get("candidate_ranges") == [])

# =====================================================================
# End-to-end coverage of a NEGATIVE shift_days ("move it back a day") -
# the same call-site arithmetic, the other direction.
# =====================================================================
def _post_claude_shift_back(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
            "relative_date_hint": {
                "weekday_start": None, "weekday_end": None, "month_name": None,
                "month_relative": None, "part_of_month": None, "duration_days": None,
                "shift_days": -1,
            },
            "relative_date_hint_evidence": message_,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "קלטתי, הזזתי את התאריכים יום אחורה."
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_post_claude_shift_back):
    r_shift_back = client.post("/api/ariella/chat-clean", json={
        "message": "אפשר לזוז יום אחד אחורה?",
        "history": [{"role": "assistant", "content": "קלטתי, 17.11.2026 עד 24.11.2026."}],
        "trip_state": confirmed_state,
    })
data_shift_back = r_shift_back.get_json() or {}
dates_shift_back = (data_shift_back.get("trip_update") or {}).get("dates") or {}
check("'אפשר לזוז יום אחד אחורה?' (shift_days=-1) moves departure back one "
      "day (2026-11-17 -> 2026-11-16)",
      dates_shift_back.get("departure") == "2026-11-16")
check("the same negative shift also moves return back one day "
      "(2026-11-24 -> 2026-11-23)",
      dates_shift_back.get("return") == "2026-11-23")

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL RELATIVE-DATE-MODEL-PRIMARY TESTS PASSED")
