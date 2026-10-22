"""QA for Shlomo's run-9 directive (21.10.2026, qa/reports/2026-10-21-
stage1-live-run9.md on branch shaked, a08b053, 0/5 passed):

"עוצרים את תיקוני הפרומפט לבעיה הזו. שלושה סבבים בלי נתונים לא שינו את
התוצאה. מכאן עובדים רק לפי נתונים. משימה 1, דחופה: PR קטן של אבחון בלבד,
בלי שינוי התנהגות."

After three rounds of prompt-only fixes (PR #117, #120, #122) still left
post-summary date-change requests silently dropped in 0/4 of Shaked's own
live repros, Shlomo's explicit decision is to stop guessing at the prompt
and instrument the actual pipeline instead - a diagnostics-only change,
with NO behavior change, that records on every turn where the customer
already has confirmed dates:

- the EXTRACTOR's own parsed output: relative_date_hint (incl. shift_days),
  dates.departure/return as the extractor itself returned them, whether
  dates_evidence came back at all (+ its length, never its text), and
  whether the raw JSON failed to parse at all;
- every gate that can drop a date change or a shift this turn, with a
  short gate name + outcome: extractor_evidence (the dates_evidence
  verification gate), guided (the guided-extraction dispatcher), sticky_lock
  (the re-lock-to-prior-dates branch), shift_days (the relative shift
  mechanism, model-evidence or regex-fallback sourced);
- whether a candidate was produced and/or the authoritative dates actually
  changed by the end of this turn's date handling.

Recorded as a new "dates_pipeline" diagnostic event (ai_usage.py), exported
via /admin/ai-usage.csv exactly like every other diagnostic event already
in DIAGNOSTIC_EVENT_SOURCES - never the customer's own message text, only
structured fields/presence/length/short labels, per Shlomo's explicit
instruction.

Run: python3 tools/qa_run9_dates_pipeline_diagnostics.py
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
from werkzeug.security import generate_password_hash

DB = database.DB_PATH
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
            ("QA Run9 Dates Pipeline", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def _latest_row(member_id):
    rows = [
        r for r in ai_usage.diagnostic_rows("dates_pipeline", include_test=True)
        if r.get("member_id") == member_id
    ]
    return rows[0] if rows else None


# =====================================================================
# Direct unit coverage: event source registration + record/read round-trip.
# =====================================================================
check("dates_pipeline registered as a valid diagnostic event source",
      "dates_pipeline" in ai_usage.DIAGNOSTIC_EVENT_SOURCES)

ai_usage.set_ai_usage_context(member_id=None, is_test=True)
ai_usage.record_diagnostic_event("dates_pipeline", {
    "extractor": {"relative_date_hint": {"shift_days": 1}, "dates_departure": None, "dates_return": None,
                  "dates_evidence_present": False, "dates_evidence_len": 0, "parse_error": False},
    "gates": [{"gate": "shift_days", "outcome": "candidate_created", "source": "model_evidence"}],
    "result": {"candidate_created": True, "dates_changed": False},
})
_direct_rows = ai_usage.diagnostic_rows("dates_pipeline", include_test=True)
check("dates_pipeline: a row was written and comes back via diagnostic_rows",
      bool(_direct_rows))
check("dates_pipeline: round-trips the exact structure given (gates list included)",
      bool(_direct_rows) and json.loads(_direct_rows[0]["details"])["gates"] == [
          {"gate": "shift_days", "outcome": "candidate_created", "source": "model_evidence"}
      ])
ai_usage.clear_ai_usage_context()


# =====================================================================
# Direct unit coverage: _extract_trip_update's new parse-error flag.
# =====================================================================
key = os.getenv("ANTHROPIC_API_KEY", "test-key-not-real")
model = "claude-sonnet-5"
with patch.object(chat, "_post_claude", return_value="not valid json at all {{{"):
    _result = chat._extract_trip_update(key, model, [], "שלום", {})
check("_extract_trip_update returns 13 elements now (baggage_evidence added "
      "for dry-run 5b's sticky-baggage guard, alongside extractor_parse_error + "
      "extractor_diag appended earlier once the real run-9 root cause - "
      "truncation - was confirmed)",
      len(_result) == 13)
check("_extract_trip_update: a raw response that isn't valid JSON sets extractor_parse_error=True",
      _result[-2] is True)
check("_extract_trip_update: extractor_diag is a dict with no customer text, "
      "and retried=False since no truncation signal was present (a bare "
      "mocked return_value never sets stop_reason)",
      isinstance(_result[-1], dict) and _result[-1].get("retried") is False)
with patch.object(chat, "_post_claude", return_value=json.dumps({"trip_update": {}})):
    _result_ok = chat._extract_trip_update(key, model, [], "שלום", {})
check("_extract_trip_update: a well-formed (if minimal) JSON response sets extractor_parse_error=False",
      _result_ok[-2] is False)


# =====================================================================
# End-to-end A: a real shift_days request, model-evidence sourced (the
# PRIMARY path) - a verified relative_date_hint.shift_days. Covers run-9's
# "the model understands and computes the right dates in text, but the
# state candidate never gets created" failure mode, from the gate's own
# point of view (was the model's shift_days ever being supplied and
# verified in the first place?).
# =====================================================================
m_shift_model = _make_member("qa-run9-shift-model@example.com")
shift_state = {
    "destination": {"places": ["טביליסי"], "mode": "specific", "status": "known"},
    "destination_airports": ["TBS"],
    "travelers": {"adults": 2},
    "dates": {"departure": "2027-05-10", "return": "2027-05-14", "needs_confirmation": False},
    "requested_services": ["flights"],
    "session_status": {"flights": "active", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
    "active_session": "flights",
    "guided": {"current_question": "travelers", "attempts": 0, "answered": ["dates"]},
}
database.save_ariella_conversation(m_shift_model, [
    {"role": "user", "content": "טביליסי, 10-14 במאי 2027"},
    {"role": "assistant", "content": "קלטתי - טביליסי, 10-14 במאי. כמה נוסעים?"},
], dict(shift_state))


def _fake_shift_model(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {},
            "restart_request": False, "restart_evidence": None, "dates_evidence": None,
            "destination_evidence": None,
            "relative_date_hint": {
                "weekday_start": None, "weekday_end": None, "month_name": None, "month_relative": None,
                "part_of_month": None, "duration_days": None, "shift_days": 1,
            },
            "relative_date_hint_evidence": "אפשר לזוז יום אחד קדימה?",
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "תשובה לדוגמה."
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_shift_model):
    whatsapp_bridge.ariella_turn(m_shift_model, "אפשר לזוז יום אחד קדימה?")
_row_shift_model = _latest_row(m_shift_model)
check("end-to-end A: a dates_pipeline row was written for a post-close shift request",
      _row_shift_model is not None)
if _row_shift_model is not None:
    _details = json.loads(_row_shift_model["details"])
    check("end-to-end A: extractor.relative_date_hint.shift_days recorded as 1",
          (_details.get("extractor") or {}).get("relative_date_hint", {}).get("shift_days") == 1)
    check("end-to-end A: the shift_days gate recorded as candidate_created, source=model_evidence",
          {"gate": "shift_days", "outcome": "candidate_created", "source": "model_evidence"} in _details.get("gates", []))
    check("end-to-end A: result.candidate_created is True",
          (_details.get("result") or {}).get("candidate_created") is True)
    check("end-to-end A: parse_error is False (the mocked JSON was well-formed)",
          (_details.get("extractor") or {}).get("parse_error") is False)
    check("end-to-end A: relative_date_hint_evidence_present is True and _len > 0 "
          "(presence/length only, never the quote itself)",
          (_details.get("extractor") or {}).get("relative_date_hint_evidence_present") is True
          and (_details.get("extractor") or {}).get("relative_date_hint_evidence_len", 0) > 0)
    check("end-to-end A: the result carries the literal final departure/return/"
          "needs_confirmation this turn settled on, not just a changed boolean",
          (_details.get("result") or {}).get("final_departure") == "2027-05-10"
          and (_details.get("result") or {}).get("final_return") == "2027-05-14"
          and (_details.get("result") or {}).get("final_needs_confirmation") is True)


# =====================================================================
# End-to-end B: the regex-fallback path - model supplies no usable
# relative_date_hint at all, but the plain phrasing still matches
# _deterministic_shift_days_fallback.
# =====================================================================
m_shift_regex = _make_member("qa-run9-shift-regex@example.com")
database.save_ariella_conversation(m_shift_regex, [
    {"role": "user", "content": "טביליסי, 10-14 במאי 2027"},
    {"role": "assistant", "content": "קלטתי - טביליסי, 10-14 במאי. כמה נוסעים?"},
], dict(shift_state))


def _fake_shift_regex(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None,
            "relative_date_hint": None, "relative_date_hint_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "תשובה לדוגמה."
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_shift_regex):
    whatsapp_bridge.ariella_turn(m_shift_regex, "אפשר לזוז יום אחד קדימה?")
_row_shift_regex = _latest_row(m_shift_regex)
check("end-to-end B: a dates_pipeline row was written when the model gave no usable hint",
      _row_shift_regex is not None)
if _row_shift_regex is not None:
    _details_b = json.loads(_row_shift_regex["details"])
    check("end-to-end B: the shift_days gate recorded as candidate_created, source=regex_fallback "
          "(the model's own structured extraction missed it this turn)",
          {"gate": "shift_days", "outcome": "candidate_created", "source": "regex_fallback"} in _details_b.get("gates", []))
    check("end-to-end B: extractor.relative_date_hint recorded as None/null (confirms the model-side miss)",
          (_details_b.get("extractor") or {}).get("relative_date_hint") is None)


# =====================================================================
# End-to-end C: run-9's exact repro shape - POST-SUMMARY (all domains
# complete/declined), customer asks to change dates, and the model
# supplies NOTHING at all this turn (no dates, no relative_date_hint, no
# dates_evidence) - the silent-drop failure mode Shaked's report
# describes ("ה-state לא משתנה: אין candidate ואין dates").
# =====================================================================
m_silent = _make_member("qa-run9-silent-drop@example.com")
post_summary_state = {
    "destination": {"places": ["טורינו"], "mode": "specific", "status": "known"},
    "destination_airports": ["TRN"],
    "travelers": {"adults": 2},
    "dates": {"departure": "2027-06-10", "return": "2027-06-14", "needs_confirmation": False},
    "requested_services": ["flights"],
    "session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
    "active_session": "flights",
    "ready_for_summary": True,
    "flight": {"baggage": ["checked_bag"]},
}
database.save_ariella_conversation(m_silent, [
    {"role": "user", "content": "טורינו, 10-14 ביוני 2027, זוג, מזוודה"},
    {"role": "assistant", "content": "מאשרת שהכל סגור! חופשה נעימה! טורינו, 10-14 ביוני 2027."},
], dict(post_summary_state))


def _fake_silent_drop(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None,
            "relative_date_hint": None, "relative_date_hint_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "בשמחה, אשנה את זה - רגע אחת."
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_silent_drop):
    whatsapp_bridge.ariella_turn(m_silent, "אפשר בעצם לדחות את הטיסה בשבוע?")
_row_silent = _latest_row(m_silent)
check("end-to-end C (run-9's own repro shape): a dates_pipeline row was written post-summary",
      _row_silent is not None)
if _row_silent is not None:
    _details_c = json.loads(_row_silent["details"])
    check("end-to-end C: extractor_evidence gate recorded as no_differing_date (nothing to verify)",
          {"gate": "extractor_evidence", "outcome": "no_differing_date"} in _details_c.get("gates", []))
    check("end-to-end C: guided gate recorded as no_dates_update (guided dispatch is gated off post-summary)",
          any(g.get("gate") == "guided" and g.get("outcome") == "no_dates_update" for g in _details_c.get("gates", [])))
    check("end-to-end C: sticky_lock gate recorded as relocked_to_prior - this IS the silent-drop moment",
          {"gate": "sticky_lock", "outcome": "relocked_to_prior"} in _details_c.get("gates", []))
    check("end-to-end C: shift_days gate recorded as no_shift_detected (the model supplied nothing, "
          "and the free-text phrasing 'בשבוע' doesn't match the plain regex fallback either)",
          any(g.get("gate") == "shift_days" and g.get("outcome") == "no_shift_detected" for g in _details_c.get("gates", [])))
    check("end-to-end C: result.dates_changed is False - confirms the customer's request was dropped",
          (_details_c.get("result") or {}).get("dates_changed") is False)
    check("end-to-end C: result.candidate_created is False",
          (_details_c.get("result") or {}).get("candidate_created") is False)
    check("end-to-end C: relative_date_hint_evidence_present is False and _len is 0 "
          "(the model supplied nothing at all this turn)",
          (_details_c.get("extractor") or {}).get("relative_date_hint_evidence_present") is False
          and (_details_c.get("extractor") or {}).get("relative_date_hint_evidence_len", -1) == 0)
    check("end-to-end C: result.final_departure/final_return stayed exactly the "
          "pre-existing dates - the literal values the silent drop left behind",
          (_details_c.get("result") or {}).get("final_departure") == "2027-06-10"
          and (_details_c.get("result") or {}).get("final_return") == "2027-06-14")


# =====================================================================
# End-to-end D: dates_evidence present but NOT verified (a fabricated/
# unmatched quote) - the second of the two silent-failure shapes Shlomo's
# relay explicitly named ("present"=true, "verified"=false).
# =====================================================================
m_unverified = _make_member("qa-run9-evidence-unverified@example.com")
database.save_ariella_conversation(m_unverified, [
    {"role": "user", "content": "טביליסי, 10-14 במאי 2027"},
    {"role": "assistant", "content": "קלטתי - טביליסי, 10-14 במאי. כמה נוסעים?"},
], dict(shift_state))


def _fake_unverified(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {"dates": {"departure": "2027-05-12", "return": "2027-05-16"}},
            "restart_request": False, "restart_evidence": None,
            "dates_evidence": "ציטוט שלא קיים בהודעה בכלל", "destination_evidence": None,
            "relative_date_hint": None, "relative_date_hint_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "תשובה לדוגמה."
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_unverified):
    whatsapp_bridge.ariella_turn(m_unverified, "משהו אחר לגמרי")
_row_unverified = _latest_row(m_unverified)
check("end-to-end D: a dates_pipeline row was written",
      _row_unverified is not None)
if _row_unverified is not None:
    _details_d = json.loads(_row_unverified["details"])
    check("end-to-end D: extractor_evidence gate recorded as evidence_not_verified "
          "(the extractor claimed differing dates but the quote behind it doesn't match the message)",
          {"gate": "extractor_evidence", "outcome": "evidence_not_verified"} in _details_d.get("gates", []))
    check("end-to-end D: extractor.dates_evidence_present is True and dates_evidence_len > 0 "
          "(presence/length only - never the quote text itself)",
          (_details_d.get("extractor") or {}).get("dates_evidence_present") is True
          and (_details_d.get("extractor") or {}).get("dates_evidence_len", 0) > 0)
    check("end-to-end D: the fabricated quote text itself never appears anywhere in the recorded details",
          "ציטוט שלא קיים בהודעה בכלל" not in _row_unverified["details"])


# =====================================================================
# No customer text anywhere, on any of the above rows (Shlomo's explicit
# instruction) - every row's details blob is scanned for each turn's own
# customer message text.
# =====================================================================
_all_customer_messages = [
    "אפשר לזוז יום אחד קדימה?",
    "אפשר בעצם לדחות את הטיסה בשבוע?",
    "משהו אחר לגמרי",
]
_no_leak = True
for _row in (_row_shift_model, _row_shift_regex, _row_silent, _row_unverified):
    if _row is None:
        continue
    for _msg in _all_customer_messages:
        if _msg in _row["details"]:
            _no_leak = False
check("no customer message text leaks into any dates_pipeline row's details across all four end-to-end scenarios",
      _no_leak)


# =====================================================================
# Regression: a turn where the customer has NO prior confirmed dates yet
# writes no dates_pipeline row at all - the event is scoped exactly like
# dates_change, only when sticky-locking even matters.
# =====================================================================
m_no_prior = _make_member("qa-run9-no-prior-dates@example.com")
no_dates_state = {
    "destination": {"places": ["וינה"], "mode": "specific", "status": "known"},
    "travelers": {"adults": 2},
    "requested_services": ["flights"],
    "session_status": {"flights": "active", "lodging": "pending", "car": "pending", "trip_planning": "pending"},
    "active_session": "flights",
}
database.save_ariella_conversation(m_no_prior, [
    {"role": "user", "content": "וינה, זוג"},
    {"role": "assistant", "content": "קלטתי - וינה. מתי תרצו לטוס?"},
], dict(no_dates_state))


def _fake_no_prior(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None,
            "relative_date_hint": None, "relative_date_hint_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "תשובה לדוגמה."
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_no_prior):
    whatsapp_bridge.ariella_turn(m_no_prior, "סוף מאי")
check("regression: a turn with no prior confirmed dates writes no dates_pipeline row",
      _latest_row(m_no_prior) is None)


if FAILED:
    print(f"\n{len(FAILED)} CHECK(S) FAILED:")
    for name in FAILED:
        print(f"  - {name}")
    sys.exit(1)
print("\nALL RUN-9 DATES-PIPELINE-DIAGNOSTICS TESTS PASSED")
