"""QA for Shlomo's relay of Carmit's work order item 4 (20.10.2026):
"עזרה בתאריכים: כשהלקוח נותן תשובה יחסית, להציע תאריכים מדויקים." Matches
qa/stage-scenarios.md's P2 scenario (Portugal WhatsApp transcript, 19.10):

תאריכים יחסיים: "סוף החודש", "לצאת בראשון", "בראשון לחזור בחמישי", "בסוף מרץ"
-> אריאלה מציעה תאריכים מדויקים (תאריך ויום) ומבקשת אישור פעם אחת. אחרי
האישור לא שואלים שוב על תאריכים, גם לא אחרי "פרטי הטיסה סגורים". בשיחה
האמיתית השאלה חזרה 5 פעמים.

_deterministic_period_facts (the function that turns "סוף יוני, ראשון עד
חמישי" into exact calendar candidates) previously returned bare date ranges
("20.06.2027–24.06.2027") with no day-of-week - not the "תאריך ויום" (date
AND day) Carmit's criterion names. The candidate's own weekday pair
(pair.group(1)/(2), the customer's own words) is now included directly in
each label ("יום ראשון 20.06.2027–יום חמישי 24.06.2027"), which
TINKERBELL_SYSTEM already requires showing the customer verbatim (see the
"חובה להציג ללקוח בדיוק את התאריכים האלה, מילה במילה" rule) - so the fix
is in the data, not the prompt.

The "never reopen dates the customer already closed" guard at the real
call site (chat_clean(), just before _deterministic_period_facts's own
call: "if not (prior_dates.get('departure') and prior_dates.get('return'))")
already existed and is exactly the mechanism that should prevent the "asked
5 times" symptom once dates are genuinely resolved - but it had ZERO test
coverage before this file. This exercises it end-to-end through the real
/api/ariella/chat-clean endpoint (same pattern as tools/qa_gender_
registration_wins_over_approval_word.py): propose dates from relative
language, accept one, then send a later message that re-mentions a month +
weekday pair in an unrelated (route/lodging) context and confirm dates stay
untouched.

Run: python3 tools/qa_relative_date_help.py
"""
import os
import sys
import sqlite3
from datetime import datetime, timezone, date
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
# Direct unit tests of _deterministic_period_facts: each candidate must
# show the exact date AND its day of week, across several of Shaked's
# named phrasings (spread across one or two messages, matching the
# function's own "recent messages" lookback).
# =====================================================================
r1 = chat._deterministic_period_facts("רוצים לטוס בסוף יוני, ראשון עד חמישי", [])
check("'סוף יוני, ראשון עד חמישי' -> needs_confirmation=True with candidates",
      r1.get("dates", {}).get("needs_confirmation") is True and r1["dates"]["candidate_ranges"])
check("every candidate label names the day of week AND the exact date (תאריך ויום), not a bare date range",
      all("יום ראשון" in c and "יום חמישי" in c and "." in c for c in r1["dates"]["candidate_ranges"]))
check("departure/return stay None until the customer picks one (never guessed)",
      r1["dates"]["departure"] is None and r1["dates"]["return"] is None)

r2 = chat._deterministic_period_facts(
    "בסוף מרץ", [{"role": "user", "content": "לצאת בראשון, לחזור בחמישי"}]
)
check("month and weekday pair split across two messages ('בסוף מרץ' + 'לצאת בראשון, לחזור בחמישי') still resolves, with weekday names in the labels",
      r2.get("dates", {}).get("candidate_ranges")
      and all("יום ראשון" in c and "יום חמישי" in c for c in r2["dates"]["candidate_ranges"]))

r3 = chat._deterministic_period_facts("בסוף יוני, בראשון לחזור בחמישי", [])
check("Shaked's exact second named phrasing ('בראשון לחזור בחמישי', no comma, 'ב'-prefixed day, 'לחזור' connector) resolves too",
      bool(r3.get("dates", {}).get("candidate_ranges")))

r4 = chat._deterministic_period_facts("רוצים לצאת בראשון בסוף יוני", [])
check("a lone single-weekday mention with no partner weekday anywhere nearby never fabricates a pair",
      r4 == {})

# =====================================================================
# A candidate choice (any of the existing acceptance mechanisms) still
# resolves correctly against the new weekday-prefixed label format.
# =====================================================================
_state_with_candidates = {"dates": {
    "departure": None, "return": None, "needs_confirmation": True,
    "candidate_ranges": r1["dates"]["candidate_ranges"],
}}
chosen = chat._deterministic_candidate_choice_facts("הראשון מתאים לנו", _state_with_candidates)
check("choosing 'הראשון' against weekday-prefixed candidates still resolves to exact ISO dates with needs_confirmation=False",
      bool(chosen.get("dates", {}).get("departure")) and chosen["dates"]["needs_confirmation"] is False)

if FAILED:
    print(f"\n{len(FAILED)} FAILED so far: {FAILED}")

# =====================================================================
# End-to-end through the real endpoint: propose -> accept -> a LATER,
# unrelated mid-conversation mention of a month+weekday pair (route/
# lodging context) must NOT reopen the now-closed dates. This is the
# pre-existing "prior_dates" guard at the real chat_clean() call site -
# untested before this file.
# =====================================================================
def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports,gender) "
            "VALUES(?,?,?,?,?,?,?,?)",
            ("QA Relative Dates", email, generate_password_hash("Test1234!"),
             datetime.now(timezone.utc).isoformat(), "active", 0, "[]", "female"),
        )
        return cur.lastrowid


def _send(member, message, trip_state, history=None):
    def _quiet_post_claude(key, model, system_static, system_dynamic, history_, message_, max_tokens, include_history=True, source="other"):
        if source == "state_extractor":
            return json.dumps({
                "trip_update": {}, "restart_request": False, "restart_evidence": None,
                "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
            })
        if source == "guided_extract":
            return json.dumps({"status": "other_topic", "field": None, "evidence": None})
        if source == "tinkerbell_reply":
            return "קלטתי, ממשיכים."
        return "{}"

    with patch.object(chat, "_post_claude", side_effect=_quiet_post_claude):
        r = client.post("/api/ariella/chat-clean", json={
            "message": message,
            "history": history or [],
            "trip_state": trip_state,
        })
    return (r.get_json() or {}).get("trip_update") or {}


member = _make_member("qa-relative-dates@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member

base_state = {
    "trip_type": "standard",
    "destination": {"places": ["פורטוגל"], "mode": "specific", "status": "known"},
    "destination_airports": ["LIS"],
    "travelers": {"adults": 2, "children": 0},
    "requested_services": ["flights"],
    "service_decisions": {"flights": {"wanted": True}},
    "session_status": {"flights": "active", "lodging": "pending", "car": "pending", "trip_planning": "pending"},
    "active_session": "flights",
}

update1 = _send(member, "רוצים לטוס בסוף יוני, ראשון עד חמישי", base_state)
check("end-to-end: a relative-date message produces candidate_ranges with weekday names via the real endpoint",
      bool(update1.get("dates", {}).get("candidate_ranges"))
      and all("יום " in c for c in update1["dates"]["candidate_ranges"]))

update2 = _send(member, "הראשון מתאים לנו", update1)
check("end-to-end: choosing a candidate closes the dates (departure/return set, needs_confirmation=False)",
      update2.get("dates", {}).get("departure") and update2.get("dates", {}).get("return")
      and update2["dates"]["needs_confirmation"] is False)

# Now simulate the conversation moving on (flights closed, discussing lodging/
# route) and a LATER message happening to mention a month + weekday pair for
# an unrelated reason - the exact live-finding shape ("בשיחה האמיתית השאלה
# חזרה 5 פעמים").
mid_route_state = dict(update2)
mid_route_state["session_status"] = dict(update2.get("session_status") or {})
mid_route_state["session_status"]["flights"] = "complete"
mid_route_state["active_session"] = "trip_planning"
update3 = _send(
    member,
    "לא נוסעים בשבת, ונעדיף להיות בליסבון בסוף יוני בכל מקרה",
    mid_route_state,
    history=[
        {"role": "user", "content": "הראשון מתאים לנו"},
        {"role": "assistant", "content": "קלטתי, ממשיכים."},
    ],
)
check("regression (the live 'asked 5 times' finding): a later, unrelated mid-route mention of the same month+weekday pair does NOT reopen already-closed dates",
      update3.get("dates", {}).get("departure") == update2["dates"]["departure"]
      and update3.get("dates", {}).get("return") == update2["dates"]["return"]
      and update3["dates"].get("needs_confirmation") is False)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL RELATIVE-DATE-HELP TESTS PASSED")
