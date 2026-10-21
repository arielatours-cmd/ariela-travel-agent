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
# Shlomo's relay of the business owner's review (20.10.2026): "סוף
# החודש" was proposing 17.11 (the OLD window started 13 days before
# month-end, which for a 30-day month is day 17 - genuinely mid-month)
# alongside a second candidate on day 30 whose week-long return spilled
# into December. Both departures must now fall in the LAST ~10 days of
# the requested month - a genuine reading of "end of month".
# =====================================================================
r_end = chat._candidate_dates_from_relative_hint(
    {"month_relative": "next", "part_of_month": "end", "duration_days": 7}
)
import re as _re_qa
_end_departure_days = [
    int(_re_qa.search(r"(\d{2})\.11\.2026", c).group(1))
    for c in r_end["dates"]["candidate_ranges"]
]
check("'סוף החודש הבא' (November, 30 days): every candidate's DEPARTURE "
      "falls in the last 10 days of November (21-30), never mid-month "
      f"like the old 17.11 bug - got departures {_end_departure_days}",
      all(d >= 21 for d in _end_departure_days))

r_start = chat._candidate_dates_from_relative_hint(
    {"month_relative": "next", "part_of_month": "start", "duration_days": 7}
)
_start_departure_days = [
    int(_re_qa.search(r"(\d{2})\.11\.2026", c).group(1))
    for c in r_start["dates"]["candidate_ranges"]
]
check("'תחילת החודש הבא' candidates' departures fall in the first 10 days "
      f"(1-10) - got departures {_start_departure_days}",
      all(d <= 10 for d in _start_departure_days))

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
# "אפשר לזוז יום אחד קדימה?" after exact dates are already known PROPOSES
# the shifted dates as a single pending candidate - never auto-commits,
# per Shlomo's relay of Shaked's live stage-1 run-2 finding (critical):
# the first version auto-applied the shift immediately, but Tinkerbell's
# own reply still asked for confirmation (since the customer phrased it
# as a question), and the customer's "כן" then had nothing left to do,
# so a later "סגרנו" claim sat next to the OLD, never-actually-changed
# dates. A relative-date change must always go through the same explicit
# confirmation step as every other relative-date candidate.
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
        return "בטח, 18.11.2026 עד 25.11.2026 - מתאים?"
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
check("'אפשר לזוז יום אחד קדימה?' does NOT change departure/return yet - "
      "they stay at the last-CONFIRMED values until the customer actually "
      "confirms the proposal",
      dates_shift.get("departure") == "2026-11-17" and dates_shift.get("return") == "2026-11-24")
check("the shift is offered as exactly ONE pending candidate "
      "(18.11-25.11), needs_confirmation=True - never auto-applied",
      dates_shift.get("needs_confirmation") is True
      and len(dates_shift.get("candidate_ranges") or []) == 1
      and "18.11.2026" in dates_shift["candidate_ranges"][0]
      and "25.11.2026" in dates_shift["candidate_ranges"][0])

# Second turn: the customer confirms the pending shift candidate with a
# plain "כן" - this must reuse the EXISTING single-candidate-acceptance
# mechanism (_accept_single_proposed_date_range) and actually commit it.
with patch.object(chat, "_post_claude", side_effect=_post_claude_no_hint):
    r_shift_confirm = client.post("/api/ariella/chat-clean", json={
        "message": "כן",
        "history": [{"role": "assistant", "content": "בטח, 18.11.2026 עד 25.11.2026 - מתאים?"}],
        "trip_state": dict(confirmed_state, dates=dates_shift),
    })
data_shift_confirm = r_shift_confirm.get_json() or {}
dates_shift_confirm = (data_shift_confirm.get("trip_update") or {}).get("dates") or {}
check("confirming the pending shift ('כן') actually commits the shifted "
      "dates (2026-11-17 -> 2026-11-18, 2026-11-24 -> 2026-11-25)",
      dates_shift_confirm.get("departure") == "2026-11-18"
      and dates_shift_confirm.get("return") == "2026-11-25")
check("after confirming, needs_confirmation is False and candidate_ranges "
      "is cleared - this is now a settled, confirmed change",
      dates_shift_confirm.get("needs_confirmation") is False
      and dates_shift_confirm.get("candidate_ranges") == [])

# =====================================================================
# End-to-end coverage of a NEGATIVE shift_days ("move it back a day") -
# same propose-then-confirm shape, the other direction.
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
        return "בטח, 16.11.2026 עד 23.11.2026 - מתאים?"
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_post_claude_shift_back):
    r_shift_back = client.post("/api/ariella/chat-clean", json={
        "message": "אפשר לזוז יום אחד אחורה?",
        "history": [{"role": "assistant", "content": "קלטתי, 17.11.2026 עד 24.11.2026."}],
        "trip_state": confirmed_state,
    })
data_shift_back = r_shift_back.get_json() or {}
dates_shift_back = (data_shift_back.get("trip_update") or {}).get("dates") or {}
check("negative shift also only proposes a pending candidate "
      "(16.11-23.11), departure/return unchanged until confirmed",
      dates_shift_back.get("departure") == "2026-11-17"
      and dates_shift_back.get("return") == "2026-11-24"
      and dates_shift_back.get("needs_confirmation") is True
      and len(dates_shift_back.get("candidate_ranges") or []) == 1)

with patch.object(chat, "_post_claude", side_effect=_post_claude_no_hint):
    r_shift_back_confirm = client.post("/api/ariella/chat-clean", json={
        "message": "כן",
        "history": [{"role": "assistant", "content": "בטח, 16.11.2026 עד 23.11.2026 - מתאים?"}],
        "trip_state": dict(confirmed_state, dates=dates_shift_back),
    })
data_shift_back_confirm = r_shift_back_confirm.get_json() or {}
dates_shift_back_confirm = (data_shift_back_confirm.get("trip_update") or {}).get("dates") or {}
check("confirming the pending negative shift commits departure back one "
      "day (2026-11-17 -> 2026-11-16) and return back one day "
      "(2026-11-24 -> 2026-11-23)",
      dates_shift_back_confirm.get("departure") == "2026-11-16"
      and dates_shift_back_confirm.get("return") == "2026-11-23")

# =====================================================================
# Direct coverage of _deterministic_shift_days_fallback - per Shlomo's
# relay of Shaked's own diagnosis (stage-1 run-2): the live bug may have
# been the model's own shift_days extraction never returning verified
# evidence at all, leaving the shift silently dropped with no fallback.
# =====================================================================
check("direct: 'לזוז יום אחד אחורה' resolves to -1",
      chat._deterministic_shift_days_fallback("אפשר לזוז יום אחד אחורה?") == -1)
check("direct: 'לזוז יום אחד קדימה' resolves to +1",
      chat._deterministic_shift_days_fallback("אפשר לזוז יום אחד קדימה?") == 1)
check("direct: 'לזוז 3 ימים אחורה' resolves to -3",
      chat._deterministic_shift_days_fallback("אפשר לזוז 3 ימים אחורה?") == -3)
check("direct: unrelated text resolves to None - never a false positive",
      chat._deterministic_shift_days_fallback("מה השעה הטיסה?") is None)

# End-to-end: the model produces NO shift_days at all (a genuine
# extraction miss) - the regex fallback still catches the plain "move it
# back a day" phrasing and proposes the correct pending candidate.
def _post_claude_shift_no_model_hint(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
            "relative_date_hint": None, "relative_date_hint_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "בטח, 16.11.2026 עד 23.11.2026 - מתאים?"
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_post_claude_shift_no_model_hint):
    r_shift_fallback = client.post("/api/ariella/chat-clean", json={
        "message": "אפשר לזוז יום אחד אחורה?",
        "history": [{"role": "assistant", "content": "קלטתי, 17.11.2026 עד 24.11.2026."}],
        "trip_state": confirmed_state,
    })
data_shift_fallback = r_shift_fallback.get_json() or {}
dates_shift_fallback = (data_shift_fallback.get("trip_update") or {}).get("dates") or {}
check("end-to-end: with NO model-extracted shift_days at all, the regex "
      "fallback still proposes the correct pending shift candidate "
      "(16.11-23.11), departure/return unchanged until confirmed",
      dates_shift_fallback.get("departure") == "2026-11-17"
      and dates_shift_fallback.get("return") == "2026-11-24"
      and dates_shift_fallback.get("needs_confirmation") is True
      and len(dates_shift_fallback.get("candidate_ranges") or []) == 1)

# =====================================================================
# Regression (Shaked's rejection of the first version of this PR, which
# added _ensure_dates_closure_claim_matches_state as a word-matching
# safety net - now removed entirely per her review): a reply combining a
# genuine closure claim about one domain (baggage) with a genuine,
# still-pending question about another (dates) must reach the customer
# completely untouched - the word "סגרנו" alone is not a dates-closure
# claim at all. The real fix (shift_days only ever proposes, "כן" alone
# commits) is the whole mechanism now - no reply-text safety net on top
# of it.
# =====================================================================
_pending_shift_state = dict(confirmed_state, dates={
    "departure": "2026-11-17", "return": "2026-11-24", "needs_confirmation": True,
    "candidate_ranges": ["יום שלישי 20.11.2026–יום שלישי 27.11.2026"],
})


def _post_claude_baggage_closed_dates_pending(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
            "relative_date_hint": None, "relative_date_hint_evidence": None,
            "link_request": False, "link_request_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "סגרנו את הכבודה - ולגבי התאריכים, 20.11–27.11 מתאים?"
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_post_claude_baggage_closed_dates_pending):
    r_baggage_closed = client.post("/api/ariella/chat-clean", json={
        "message": "תיק יד בלבד",
        "history": [{"role": "assistant", "content": "איזו כבודה תרצו?"}],
        "trip_state": _pending_shift_state,
    })
reply_baggage_closed = str((r_baggage_closed.get_json() or {}).get("reply") or "")
check("Shaked's exact live case 1: 'סגרנו את הכבודה - ולגבי התאריכים, "
      "20.11–27.11 מתאים?' reaches the customer completely untouched - "
      "'סגרנו' about baggage is never mistaken for a dates-closure claim",
      reply_baggage_closed == "סגרנו את הכבודה - ולגבי התאריכים, 20.11–27.11 מתאים?")


# =====================================================================
# Stage-1 run-6 (Shaked/Shlomo, Paphos, severe - rework of #117, which
# Shaked rejected): a live transcript where dates got stuck on the OLD
# values through THREE consecutive turns.
#
# Turn 1: "רגע, אפשר לדחות את כל הטיסה ביום אחד?" - Ariella's reply just
# re-showed the existing summary with no reference to the request at
# all (the model's own shift_days extraction missed this phrasing - see
# below for the understanding fix, never a regex: Shaked's explicit
# instruction on THIS PR was "אל תרחיב את ה-regex", so the regex fallback
# is left exactly as it was before #117 ever touched it).
#
# Turn 2: the customer then explicitly restated the dates themselves -
# "כן, לצאת ב-24.11 ולחזור ב-1.12" - and Ariella asked "רק לוודא...
# 24.11–1.12, נכון?", immediately showing an "updated" summary that
# still had the OLD dates (23.11–30.11).
#
# Turn 3: the customer confirmed "כן" again, and the dates still never
# actually changed.
#
# Second review round (Shaked rejected the first fix - cec33ac - over a
# severe regression): that first attempt proposed the extractor's own
# UNVERIFIED differing dates as a pending single candidate instead of
# re-locking, on the theory that a dual-call evidence miss (never a real
# absence of intent) was the cause. But Shaked's review found this could
# ALSO fire on a genuinely unrelated mention with no real request behind
# it at all - a recalled PAST trip ("לפני שנתיים היינו שם 3 עד 7 ביוני")
# - creating a candidate that the customer's own NEXT "כן", answering a
# completely different question, would then silently commit. That
# candidate mechanism is REMOVED entirely (see the "elif prior_dates"
# branch's own docstring) - the evidence gate is the only way a date
# change is recognized here, exactly as before #117 ever existed.
#
# Shaked separately tested _value_has_verbatim_evidence directly and
# confirmed the quote "לצאת ב-24.11 ולחזור ב-1.12" already passes
# verification, even with a "כן, " prefix - verification only fails when
# the model itself reformats the date digit-wise while copying it (adds
# a year, adds a leading zero, or writes a combined range). The real fix:
# EXTRACTOR_SYSTEM now explicitly instructs an exact copy (no added year/
# leading zero/dash), and _value_has_verbatim_evidence tolerates digit-
# format differences as a fallback (never a word/phrase list - purely
# numeric normalization, see _normalize_date_digits_for_evidence_match).
# =====================================================================
check("regression: EXTRACTOR_SYSTEM's shift_days guidance no longer "
      "lists specific verbs with per-verb direction explanations ('לדחות'/"
      "'להקדים') - Shaked's review flagged this as contradicting the "
      "21.10 no-phrase-list decision; one general example is enough",
      "לדחות" not in chat.EXTRACTOR_SYSTEM and "להקדים" not in chat.EXTRACTOR_SYSTEM)
check("EXTRACTOR_SYSTEM's dates_evidence instruction now explicitly "
      "requires an exact copy of the message excerpt, without adding a "
      "year, a leading zero, or a dash",
      "בלי להוסיף שנה" in chat.EXTRACTOR_SYSTEM)

check("direct: _normalize_date_digits_for_evidence_match strips a "
      "leading zero",
      chat._normalize_date_digits_for_evidence_match("01.12") == "1.12")
check("direct: _normalize_date_digits_for_evidence_match drops an added "
      "year",
      chat._normalize_date_digits_for_evidence_match("24.11.2026") == "24.11")
check("direct: a date already in canonical form is left untouched",
      chat._normalize_date_digits_for_evidence_match("24.11") == "24.11")
check("direct: non-date text is never touched",
      chat._normalize_date_digits_for_evidence_match("לא חובה") == "לא חובה")

_paphos_msg = "כן, לצאת ב-24.11 ולחזור ב-1.12"
check("_value_has_verbatim_evidence: a quote with an ADDED year the "
      "message never stated still verifies (digit-format fallback)",
      chat._value_has_verbatim_evidence("24.11.2026", _paphos_msg))
check("_value_has_verbatim_evidence: a quote with an added LEADING ZERO "
      "still verifies",
      chat._value_has_verbatim_evidence("01.12", _paphos_msg))
check("regression: _value_has_verbatim_evidence still rejects a quote "
      "that is not genuinely in the message at all, even after digit "
      "normalization - this is not a license to accept fabricated dates",
      not chat._value_has_verbatim_evidence("25.11.2026", _paphos_msg))

_paphos_state = dict(
    base_state,
    destination={"places": ["פאפוס"], "mode": "specific", "status": "known"},
    destination_airports=["PFO"],
    dates={"departure": "2026-11-23", "return": "2026-11-30", "needs_confirmation": False},
)


def _post_claude_paphos_year_added(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        # The exact live #117 failure mode, per Shaked's own direct testing
        # of the verification function: the model wrote the correct new
        # dates, but its own dates_evidence quote added a year the
        # customer's message never stated.
        return json.dumps({
            "trip_update": {"dates": {"departure": "2026-11-24", "return": "2026-12-01"}},
            "restart_request": False, "restart_evidence": None,
            "dates_evidence": "24.11.2026",
            "destination_evidence": None, "trip_type_evidence": None,
            "relative_date_hint": None, "relative_date_hint_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "מעולה, עדכנתי ל-24.11–1.12."
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_post_claude_paphos_year_added):
    r_paphos = client.post("/api/ariella/chat-clean", json={
        "message": _paphos_msg,
        "history": [{"role": "assistant", "content": "קלטתי - פאפוס, 23.11–30.11.2026."}],
        "trip_state": dict(_paphos_state),
    })
dates_paphos = ((r_paphos.get_json() or {}).get("trip_update") or {}).get("dates") or {}
check("end-to-end Paphos repro: the model's dates_evidence added a year "
      "('24.11.2026') the message never stated - the new dates still "
      "commit IMMEDIATELY in this one turn, no 'רק לוודא' confirmation "
      "step needed, via the digit-format-tolerant evidence check",
      dates_paphos.get("departure") == "2026-11-24" and dates_paphos.get("return") == "2026-12-01"
      and dates_paphos.get("needs_confirmation") is False)

# Regression: when dates_evidence verifies without any digit formatting
# at all (the exact quote), the direct-commit path is unaffected.
def _post_claude_paphos_evidence_verified(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {"dates": {"departure": "2026-11-24", "return": "2026-12-01"}},
            "restart_request": False, "restart_evidence": None,
            "dates_evidence": "לצאת ב-24.11 ולחזור ב-1.12",
            "destination_evidence": None, "trip_type_evidence": None,
            "relative_date_hint": None, "relative_date_hint_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "מעולה, עדכנתי ל-24.11–1.12."
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_post_claude_paphos_evidence_verified):
    r_verified = client.post("/api/ariella/chat-clean", json={
        "message": _paphos_msg,
        "history": [{"role": "assistant", "content": "קלטתי - פאפוס, 23.11–30.11.2026."}],
        "trip_state": dict(_paphos_state),
    })
dates_verified = ((r_verified.get_json() or {}).get("trip_update") or {}).get("dates") or {}
check("regression: an exact, unreformatted dates_evidence quote still "
      "commits immediately exactly as before",
      dates_verified.get("departure") == "2026-11-24" and dates_verified.get("return") == "2026-12-01"
      and dates_verified.get("needs_confirmation") is False)

# Shaked's exact regression repro: a PAST TRIP mention with no real
# request behind it must NEVER change the dates, even when the customer's
# very next message is an unrelated "כן".
def _post_claude_past_trip_mention(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        # A hypothetical overreach: the extractor wrongly wrote the past
        # trip's dates into trip_update.dates, with no real dates_evidence
        # behind it (nothing in the message is a genuine date-CHANGE
        # request) - the worst case this regression test can exercise.
        return json.dumps({
            "trip_update": {"dates": {"departure": "2026-06-03", "return": "2026-06-07"}},
            "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
            "relative_date_hint": None, "relative_date_hint_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "איזה יופי! ומה דעתכם על מסלול למסעדות מקומיות?"
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_post_claude_past_trip_mention):
    r_past_trip = client.post("/api/ariella/chat-clean", json={
        "message": "לפני שנתיים היינו שם 3 עד 7 ביוני",
        "history": [{"role": "assistant", "content": "קלטתי - פאפוס, 23.11–30.11.2026."}],
        "trip_state": dict(_paphos_state),
    })
dates_past_trip = ((r_past_trip.get_json() or {}).get("trip_update") or {}).get("dates") or {}
check("Shaked's exact regression repro: a recalled PAST trip mention "
      "(no verified dates_evidence) never changes the locked dates - "
      "stays exactly at 23.11-30.11, needs_confirmation=False, no "
      "candidate created at all",
      dates_past_trip.get("departure") == "2026-11-23" and dates_past_trip.get("return") == "2026-11-30"
      and dates_past_trip.get("needs_confirmation") is False
      and not dates_past_trip.get("candidate_ranges"))

with patch.object(chat, "_post_claude", side_effect=_post_claude_past_trip_mention):
    r_past_trip_yes = client.post("/api/ariella/chat-clean", json={
        "message": "כן",
        "history": [{"role": "assistant", "content": "איזה יופי! ומה דעתכם על מסלול למסעדות מקומיות?"}],
        "trip_state": dict(_paphos_state, dates=dates_past_trip),
    })
dates_past_trip_yes = ((r_past_trip_yes.get_json() or {}).get("trip_update") or {}).get("dates") or {}
check("Shaked's exact regression repro, the critical step: the "
      "customer's very next 'כן' - answering a completely UNRELATED "
      "question - never silently commits the past trip's dates either, "
      "since no candidate was ever created to accept in the first place",
      dates_past_trip_yes.get("departure") == "2026-11-23" and dates_past_trip_yes.get("return") == "2026-11-30")

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL RELATIVE-DATE-MODEL-PRIMARY TESTS PASSED")
