"""QA for Shaked's stage-1 run-8 (aa34859, 2/5) - relayed by Shlomo
(21.10.2026). PR #120 itself works (replies no longer stomped post-
summary; Sarajevo budget-after-summary and Chisinau past-trip-after-
summary both passed). Three further findings, in order:

1. EXTRACTOR still doesn't return shift_days or explicit dates after the
summary in some phrasings (Torino: "אפשר לדחות ביום" - Ariella confirmed
12-16.3 in her own free text, but no candidate was ever created in state;
Santorini: the customer wrote explicit dates 3.6-8.6, never saved). Works
fine mid-conversation (Biarritz). Shaked's own direct read of
EXTRACTOR_SYSTEM found the root cause: the relative_date_hint bullet
opens with "...ו-dates.departure/dates.return עדיין ריקים ב-state" (and
dates are STILL EMPTY in state) - but the SAME bullet's own shift_days
sub-clause requires the exact opposite ("רק כאשר dates.departure/dates.
return כבר קיימים ב-state" - only when dates ALREADY EXIST). A genuine
internal contradiction: read literally, the bullet's own opening condition
excludes the one case shift_days exists for. Combined with PR #120's own
post-summary hint emphasizing the dates are "already closed", the model
may have concluded the whole relative_date_hint/shift_days mechanism
simply didn't apply post-summary, silently dropping both paths.

Fix: EXTRACTOR_SYSTEM's relative_date_hint bullet no longer gates itself
entirely on "dates still empty" - that condition now scopes only the
weekday/month/duration fields (which describe a FRESH date window, so
naturally only matter before dates are set); shift_days is now stated
explicitly as the opposite case, valid whether dates are still open OR
already closed/shown in a summary. _post_summary_dates_context_hint's own
wording (PR #120) is reworded to match - "these are the CURRENT dates, a
request to change them is valid exactly like mid-conversation" - instead
of emphasizing they are "closed".

2. "הנה הסיכום המעודכן" (here's the updated summary) when state genuinely
did not change (severe - misleads the customer into thinking their
request was applied when it wasn't). Fix: a new TINKERBELL_SYSTEM
instruction forbidding any "updated"/"changed" framing on a returned
summary unless a real fact actually differs from what was already shown
earlier in the conversation.

3. Bug B (mixed baggage, Biarritz) reproduced again - this run (aa34859)
predates PR #121's merge, so this is the same already-fixed-pending-
review issue, not new work.

Minor findings (backlog, not actioned here): "(בכפוף לזמינות בפועל
בחיפוש)" leaking into the summary despite the prompt forbidding it;
"כבודה: 2 מזוודות" and "חשוב לך" to a couple - both already tracked as
pending minor findings (tasks #133/#134).

Run: python3 tools/qa_run8_post_summary_followups.py
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
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports,gender) "
            "VALUES(?,?,?,?,?,?,?,?)",
            ("QA Run8 Post Summary Followups", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]", "female"),
        )
        return cur.lastrowid


def _post(message, history, trip_state, member_id):
    with client.session_transaction() as sess:
        sess["member_id"] = member_id
    r = client.post("/api/ariella/chat-clean", json={
        "message": message, "history": history, "trip_state": trip_state,
    })
    return r.get_json()


# =====================================================================
# Fix 1: EXTRACTOR_SYSTEM's relative_date_hint bullet no longer contains
# the self-contradiction Shaked diagnosed.
# =====================================================================
_extractor_src = chat.EXTRACTOR_SYSTEM if isinstance(chat.EXTRACTOR_SYSTEM, str) else ""
check("fix 1: the relative_date_hint bullet no longer opens with a blanket "
      "'dates still empty' gate covering the whole bullet (the exact old "
      "contradictory phrasing is gone)",
      "לטוס (יום/זוג ימים בשבוע" in _extractor_src
      and "לטוס (יום/זוג ימים בשבוע, חלק מחודש כמו \"סוף/תחילת/אמצע החודש\" או \"החודש הבא\", ו/או משך כמו \"שבוע\"/\"עשרה ימים\") ו-dates.departure/dates.return עדיין ריקים ב-state" not in _extractor_src)
check("fix 1: shift_days' own clause now explicitly states it is valid "
      "even when dates are already locked/already shown in a summary",
      "כבר נסגרו והוצגו ללקוח" in _extractor_src
      and "תקפה גם כשהתאריכים כבר נעולים" in _extractor_src)
check("fix 1: shift_days is explicitly framed as the OPPOSITE case from "
      "the weekday/month fields (so the model can't read one blanket "
      "condition as covering both)",
      "בניגוד לשדות שלמעלה, השדה הזה תקף בדיוק הפוך" in _extractor_src)
check("regression: the weekday/month fields still note they mainly apply "
      "while dates are unset - only shift_days' own gate changed, not the "
      "general guidance for the other fields",
      "רלוונטי בעיקר כשdates.departure/dates.return עדיין ריקים ב-state" in _extractor_src
      and "אותה הערה" in _extractor_src)

_post_summary_hint_text = chat._post_summary_dates_context_hint({
    "session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
    "dates": {"departure": "2026-11-21", "return": "2026-12-05"},
})
check("fix 1: the post-summary dates hint (#120) no longer frames the "
      "dates as 'closed' - it frames them as CURRENT, with a change "
      "request being valid exactly like mid-conversation",
      "כל התחומים כבר סגורים" not in _post_summary_hint_text
      and "אלה התאריכים הנוכחיים" in _post_summary_hint_text
      and "בדיוק כמו באמצע השיחה" in _post_summary_hint_text)
check("fix 1: the hint explicitly says shift_days applies even once the "
      "dates were already shown",
      "shift_days תקף גם כשהתאריכים האלה כבר הוצגו" in _post_summary_hint_text)


# =====================================================================
# Regression: the downstream CODE path for a post-summary shift request
# (Torino-shape) and explicit new dates (Santorini-shape) still works
# correctly once the model returns shift_days/dates+evidence - the root
# cause here was the PROMPT confusing the model into never returning them
# in the first place, not a downstream code bug (already covered by PR
# #120's own QA) - this just confirms the prompt edits didn't break the
# existing, already-fixed downstream handling.
# =====================================================================
_TORINO_STATE = {
    "trip_type": "vacation",
    "destination": {"places": ["טורינו"], "mode": "specific", "status": "known"},
    "destination_airports": ["TRN"],
    "departure_airport": "TLV",
    "travelers": {"adults": 2, "children": 0},
    "dates": {"departure": "2027-03-12", "return": "2027-03-16", "needs_confirmation": False, "candidate_ranges": []},
    "requested_services": ["flights"],
    "service_decisions": {
        "flights": {"wanted": True}, "lodging": {"wanted": False},
        "car": {"wanted": False}, "trip_planning": {"wanted": False},
    },
    "session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
    "active_session": None, "next_session": None, "ready_for_summary": True,
    "budget_per_person": {"amount": 1200, "currency": "EUR"},
    "flight": {"connection_preference": "אין העדפה", "baggage": ["carry_on_only"]},
}
_TORINO_OLD_SUMMARY = (
    "סיכום החופשה: טורינו, 12.03.2027 - 16.03.2027, 2 מבוגרים. "
    "אם כל הפרטים נכונים, כתבי מאשרת."
)


def _post_claude_torino_shift(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
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
        return "בטח, 13.03.2027 עד 17.03.2027 - מתאים?"
    return "{}"


_member_torino = _make_member("qa-run8-torino@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = _member_torino
with patch.object(chat, "_post_claude", side_effect=_post_claude_torino_shift):
    r_torino = client.post("/api/ariella/chat-clean", json={
        "message": "רגע, אפשר לדחות ביום?",
        "history": [{"role": "assistant", "content": _TORINO_OLD_SUMMARY}],
        "trip_state": _TORINO_STATE,
    })
data_torino = r_torino.get_json() or {}
dates_torino = (data_torino.get("trip_update") or {}).get("dates") or {}
reply_torino = str(data_torino.get("reply") or "")
check("Torino-shape regression: once the model DOES return shift_days "
      "post-summary, the existing candidate mechanism still proposes it "
      "correctly (old dates kept until confirmed)",
      dates_torino.get("needs_confirmation") is True
      and dates_torino.get("departure") == "2027-03-12"
      and len(dates_torino.get("candidate_ranges") or []) == 1
      and "13.03.2027" in dates_torino["candidate_ranges"][0])
check("Torino-shape regression: the proposal reply reaches the customer "
      "unmolested",
      reply_torino == "בטח, 13.03.2027 עד 17.03.2027 - מתאים?")


_SANTORINI_STATE = dict(
    _TORINO_STATE,
    destination={"places": ["סנטוריני"], "mode": "specific", "status": "known"},
    destination_airports=["JTR"],
    dates={"departure": "2027-06-04", "return": "2027-06-09", "needs_confirmation": False, "candidate_ranges": []},
)
_SANTORINI_OLD_SUMMARY = (
    "סיכום החופשה: סנטוריני, 04.06.2027 - 09.06.2027, 2 מבוגרים. "
    "אם כל הפרטים נכונים, כתבי מאשרת."
)


def _post_claude_santorini_explicit(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {"dates": {"departure": "2027-06-03", "return": "2027-06-08"}},
            "restart_request": False, "restart_evidence": None,
            "dates_evidence": "3.6 ועד 8.6",
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
        return "מעולה, עדכנתי את התאריכים ל-03.06.2027 עד 08.06.2027."
    return "{}"


_member_santorini = _make_member("qa-run8-santorini@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = _member_santorini
with patch.object(chat, "_post_claude", side_effect=_post_claude_santorini_explicit):
    r_santorini = client.post("/api/ariella/chat-clean", json={
        "message": "רגע, 3.6 ועד 8.6 יתאים יותר",
        "history": [{"role": "assistant", "content": _SANTORINI_OLD_SUMMARY}],
        "trip_state": _SANTORINI_STATE,
    })
data_santorini = r_santorini.get_json() or {}
dates_santorini = (data_santorini.get("trip_update") or {}).get("dates") or {}
reply_santorini = str(data_santorini.get("reply") or "")
check("Santorini-shape regression: once the model DOES return explicit "
      "dates + verified evidence post-summary, they commit immediately",
      dates_santorini.get("departure") == "2027-06-03"
      and dates_santorini.get("return") == "2027-06-08")
check("Santorini-shape regression: the acknowledgement reply reaches the "
      "customer unmolested",
      reply_santorini == "מעולה, עדכנתי את התאריכים ל-03.06.2027 עד 08.06.2027.")


# =====================================================================
# Fix 2: TINKERBELL_SYSTEM forbids claiming the summary is "updated" when
# nothing actually changed.
# =====================================================================
_tinkerbell_src = chat.TINKERBELL_SYSTEM if isinstance(chat.TINKERBELL_SYSTEM, str) else ""
check("fix 2: TINKERBELL_SYSTEM forbids an 'updated summary' claim unless "
      "a real fact genuinely differs from what was already shown",
      "הסיכום המעודכן" in _tinkerbell_src
      and "אלא אם עובדה אמיתית בפועל" in _tinkerbell_src
      and "מטעה את הלקוח לחשוב שבקשתו בוצעה" in _tinkerbell_src)

if FAILED:
    print(f"\n{len(FAILED)} CHECK(S) FAILED:")
    for name in FAILED:
        print(f"  - {name}")
    sys.exit(1)
print("\nALL RUN8-POST-SUMMARY-FOLLOWUPS TESTS PASSED")
