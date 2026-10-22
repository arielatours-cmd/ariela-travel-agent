"""QA for run-10 #4 (22.10, Bezalel's task, report
qa/reports/2026-10-22-stage1-live-run10.md on the shaked branch):

Genoa: after the summary, explicit new dates ("9 עד 13 במאי") were saved
(evidence-gated, applied directly - no pending candidate), yet the reply
asked "רק לוודא - חוזרים לתאריכים המקוריים: 09.05–13.05?" - redundant and
factually wrong. Fix: a one-turn hint (_dates_changed_hint), set before the
reply is written: already saved, don't ask, don't call them original.
The relative-shift confirmation ("לדחות ביום" -> pending candidate that must
be confirmed) is a deliberate mechanism and stays. Per Shlomo (22.10) it is
the ONLY question: a one-turn hint (_shift_candidate_hint) tells the model to
show the shifted dates with {{DATE_OPTIONS}} and ask if they fit, never a
separate "גם את היציאה וגם את החזרה?".

Zaragoza: "נראה שהסתפק לי לתת סיכום לפי המצב הנוכחי, כולל ציון שלינה ורכב
לא נדרשים..." - the model narrating a conflict between two instructions:
_declined_domains_hint ("name the exact list of declined domains") vs. the
summary rule (declined domains never appear, the reminder is general). On
the summary turn the hint now carries the summary rule only.

No regex on the output - hints only. Offline. Run:
python3 tools/qa_run10_redundant_confirm_and_leak.py
"""
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import database  # noqa: E402
database.init_db()

import ariella_chat_clean as chat  # noqa: E402
import whatsapp_bridge  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


def _make_member(email):
    with sqlite3.connect(database.DB_PATH) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA Genoa", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


# --- Zaragoza: the declined-domains hint on the summary turn ----------------------------------
statuses = {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "declined"}
mid = chat._declined_domains_hint({"session_status": statuses})
check("mid-conversation: still the exact list of declined domains (unchanged)",
      "לינה" in mid and "השכרת רכב" in mid and "חייב לכלול את" in mid)
summ = chat._declined_domains_hint({"session_status": statuses, "ready_for_summary": True})
check("summary turn: no 'must name the exact list' instruction", "חייב לכלול את" not in summ)
check("summary turn: declined domains are not named at all", "לינה" not in summ and "השכרת רכב" not in summ)
check("summary turn: says they don't appear and the reminder is general",
      "לא מופיעים בה בכלל" in summ and "בלי לפרט" in summ)
check("summary turn: tells the model not to describe how it builds the summary", "בלי שום משפט על האופן" in summ)
check("nothing declined -> no hint either way",
      chat._declined_domains_hint({"session_status": {"flights": "complete"}, "ready_for_summary": True}) == "")

# --- Genoa: explicit new dates after the dates were set ----------------------------------------
BASE = {
    "destination": {"places": ["גנואה"], "mode": "specific", "status": "known"},
    "travelers": {"adults": 2},
    "dates": {"departure": "2027-05-07", "return": "2027-05-11", "needs_confirmation": False},
    "requested_services": ["flights"],
    "service_decisions": {"flights": {"wanted": True}},
    "session_status": {"flights": "active", "lodging": "pending", "car": "pending", "trip_planning": "pending"},
    "active_session": "trip_planning",
    "guided": {"current_question": None, "attempts": 0, "answered": ["dates", "travelers", "baggage"]},
}
seen = {}


def fake(new_dates, evidence):
    def _f(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
        if source == "state_extractor":
            return json.dumps({"restart_request": False, "restart_evidence": None,
                               "dates_evidence": evidence, "destination_evidence": None, "trip_type_evidence": None,
                               "trip_update": {"dates": new_dates} if new_dates else {}}, ensure_ascii=False)
        if source == "guided_extract":
            return json.dumps({"status": "other_topic", "field": None, "evidence": None})
        if source == "tinkerbell_reply":
            seen.setdefault("dyn", []).append(system_dynamic)
            return "עודכן."
        return "{}"
    return _f


def turn(email, message, new_dates, evidence):
    seen.clear()
    m = _make_member(email)
    database.save_ariella_conversation(m, [
        {"role": "user", "content": "גנואה, זוג, 7-11 במאי 2027"},
        {"role": "assistant", "content": "קלטתי. לתכנן גם מסלול?"},
    ], json.loads(json.dumps(BASE)))
    with patch.object(chat, "_post_claude", side_effect=fake(new_dates, evidence)):
        whatsapp_bridge.ariella_turn(m, message)
    return (database.load_ariella_conversation(m) or {}).get("trip_state") or {}, "\n".join(seen.get("dyn") or [])


st, dyn = turn("qa-r10-genoa@example.com", "בעצם 9 עד 13 במאי",
               {"departure": "2027-05-09", "return": "2027-05-13"}, "9 עד 13 במאי")
check("Genoa: explicit new dates saved as before",
      (st.get("dates") or {}).get("departure") == "2027-05-09" and (st.get("dates") or {}).get("return") == "2027-05-13")
check("Genoa: the reply's prompt carries the 'already saved, don't ask' hint",
      "כבר נשמרו בפועל" in dyn and "רק לוודא" in dyn and "מקוריים" in dyn)
check("Genoa: the hint points to the {{DATES}} placeholder (no date written by the model)", "{{DATES}}" in dyn)

st, dyn = turn("qa-r10-genoa-quiet@example.com", "מעולה, נמשיך", None, None)
check("an unrelated turn: no dates-changed hint, dates untouched",
      "כבר נשמרו בפועל" not in dyn and (st.get("dates") or {}).get("departure") == "2027-05-07")
check("...and the one-turn key isn't left in the saved state", "_dates_changed_hint" not in st)

st, dyn = turn("qa-r10-genoa-unverified@example.com", "החברים טסים 9 עד 13 במאי",
               {"departure": "2027-05-09", "return": "2027-05-13"}, "לא מופיע בהודעה")
check("unverified evidence: dates not changed, no hint",
      (st.get("dates") or {}).get("departure") == "2027-05-07" and "כבר נשמרו בפועל" not in dyn)

# --- Shift: the confirmation stays, but it shows the shifted dates directly (Shlomo, 22.10) ---
def fake_shift(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({"restart_request": False, "restart_evidence": None, "dates_evidence": None,
                           "destination_evidence": None, "trip_type_evidence": None,
                           "relative_date_hint": {"shift_days": 1}, "relative_date_hint_evidence": "לדחות ביום",
                           "trip_update": {}}, ensure_ascii=False)
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        seen.setdefault("dyn", []).append(system_dynamic)
        return "{{DATE_OPTIONS}} - מתאים?"
    return "{}"


seen.clear()
m = _make_member("qa-r10-genoa-shift@example.com")
database.save_ariella_conversation(m, [
    {"role": "user", "content": "גנואה, זוג, 7-11 במאי 2027"},
    {"role": "assistant", "content": "קלטתי. לתכנן גם מסלול?"},
], json.loads(json.dumps(BASE)))
with patch.object(chat, "_post_claude", side_effect=fake_shift):
    whatsapp_bridge.ariella_turn(m, "אפשר לדחות ביום?")
st = (database.load_ariella_conversation(m) or {}).get("trip_state") or {}
dyn = "\n".join(seen.get("dyn") or [])
d = st.get("dates") or {}
check("shift: still a pending candidate needing confirmation (decision kept)",
      d.get("needs_confirmation") is True and d.get("departure") == "2027-05-07" and len(d.get("candidate_ranges") or []) == 1)
check("shift: the hint says show {{DATE_OPTIONS}} and ask if it fits - the only confirmation",
      "{{DATE_OPTIONS}}" in dyn and "האישור היחיד" in dyn)
check("shift: the hint forbids the 'both departure and return?' intermediate question", "שאלת ביניים" in dyn)
st2, dyn2 = turn("qa-r10-genoa-noshift@example.com", "מעולה, נמשיך", None, None)
check("no shift this turn -> no shift hint", "האישור היחיד" not in dyn2 and "_shift_candidate_hint" not in st2)

# --- Direct unit check on _dates_truth_hint itself (Shlomo's follow-up on
#     #141, 22.10): while BASE above simulates the POST-summary Genoa shape
#     (active_session="trip_planning", where _dates_truth_hint is scoped
#     off entirely and _shift_candidate_hint alone carries the wording), a
#     shift request made DURING the flights stage fires _dates_truth_hint's
#     own candidates branch too, alongside _shift_candidate_hint - its
#     plural "יש אפשרויות ממתינות" framing (written for the weekday-pair/
#     duration flows, which CAN offer 2+ real options) risked Tinkerbell
#     composing a pick-one-from-a-list question around what a shift always
#     is: ONE single proposed range. Only a true single candidate switches
#     to the singular wording; a genuine multi-candidate state keeps the
#     plural one. ------------------------------------------------------
_one_candidate_state = {"active_session": "flights", "dates": {
    "needs_confirmation": True, "candidate_ranges": ["יום שישי 07.05.2027–יום שלישי 11.05.2027"],
}}
check("shift during the flights stage: _dates_truth_hint uses singular framing "
      "('one new proposal'), never the plural 'יש אפשרויות ממתינות' wording",
      "הצעת תאריכים חדשה אחת" in chat._dates_truth_hint(_one_candidate_state)
      and "יש אפשרויות ממתינות" not in chat._dates_truth_hint(_one_candidate_state))
check("...and it still asks for one direct confirmation ('מתאים לך?'-style), "
      "not a pick-one-from-a-list question",
      "שאלת אישור ישירה אחת" in chat._dates_truth_hint(_one_candidate_state))

_two_candidate_state = {"active_session": "flights", "dates": {
    "needs_confirmation": True, "candidate_ranges": ["יום א 1.6.2027–יום ו 6.6.2027", "יום ב 2.6.2027–יום ש 7.6.2027"],
}}
check("two real candidates -> the plural 'יש אפשרויות ממתינות' framing is kept",
      "יש אפשרויות ממתינות" in chat._dates_truth_hint(_two_candidate_state)
      and "הצעת תאריכים חדשה אחת" not in chat._dates_truth_hint(_two_candidate_state))

# --- The relative-shift confirmation mechanism is untouched -----------------------------------
src = open(os.path.join(os.path.dirname(__file__), "..", "ariella_chat_clean.py"), encoding="utf-8").read()
check("shift_days still creates a pending candidate (needs_confirmation=True), not touched",
      '"needs_confirmation": True, "candidate_ranges": [_shift_label]' in src)

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
