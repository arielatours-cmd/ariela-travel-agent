"""QA for Shlomo's relay (22.10.2026) of the business owner's real
diagnostics file (ceo/relay/data/2026-10-21-diagnostics-dates_pipeline-1d.csv,
branch ceo) - the actual run-9 root cause, found from genuine live data
after three rounds of structural fixes (#117/#120/#122) plus the dates_
pipeline diagnostics instrumentation (#123) that made this visible at all:

"בכל התורות שבהם לקוח ביקש שינוי אחרי הסיכום יש parse_error=true, וכל
השדות של ה-EXTRACTOR ריקים (null) ... היוצא מן הכלל הוא zd5 ... parse
תקין ... זו ההצלחה היחידה. כלומר המודל לא נכשל בהבנה. הפלט של ה-EXTRACTOR
לא נקרא כ-JSON, ולכן כל מה שהמודל הבין נזרק. ההשערה: חיתוך בגלל
max_tokens=900."

Root cause confirmed directly from the data: every live post-summary
date-change turn with parse_error=true had EVERY extractor field null -
not a model-understanding failure, a budget failure. Once the post-
summary state is large (many nested trip_update fields), 900 tokens
wasn't enough room for the EXTRACTOR's own full JSON response, so it got
cut off mid-object before _parse_trip_update ever saw a complete,
parseable value - and everything the model actually understood that turn
was silently discarded along with the truncated text. zd5 (the one
success Shaked's earlier live run saw) just happened to need a short
enough response to fit under the old budget.

Fix (one PR, per Shlomo's instructions):
1. Diagnostics: added stop_reason, output_tokens, starts_with_brace,
   ends_with_brace, retried_on_truncation to the "dates_pipeline" event's
   "extractor" section - never the customer's own text, structured
   fields/booleans only.
2. Raised the EXTRACTOR's own max_tokens from 900 to 2000 (sized for a
   full trip_update, per Shlomo's own estimate) - the primary fix, which
   alone resolves every truncation shape actually seen in the real data.
3. Backstop: on a parse failure where the raw API response's own
   stop_reason is genuinely "max_tokens" (truncation, not a different
   kind of malformed output a bigger budget wouldn't fix), retry the
   SAME extractor call exactly once with a wider ceiling still (3500).
   Capped at one retry per turn by construction (an if-block, never a
   loop or recursion) - there is no path to more than two total EXTRACTOR
   calls in a single turn.

Per Shlomo's own cost note: tokens are only billed for what the model
actually generates, so raising the ceiling costs nothing on an ordinary,
much shorter turn - it only matters on the turns that were silently
failing before.

zd4's secondary finding (dates_evidence sourced from Ariella's own prior
message, not the customer's) is explicitly deferred per Shlomo - it
should resolve itself once the candidate is correctly created in the
prior turn, and is not touched here.

Run: python3 tools/qa_run9_extractor_truncation_fix.py
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
KEY = os.getenv("ANTHROPIC_API_KEY", "test-key-not-real")
MODEL = "claude-sonnet-5"
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
            ("QA Run9 Extractor Truncation", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def _latest_row(member_id):
    rows = [
        r for r in ai_usage.diagnostic_rows("dates_pipeline", include_test=True)
        if r.get("member_id") == member_id
    ]
    return rows[0] if rows else None


# =====================================================================
# Direct unit coverage: _extract_trip_update's own retry contract.
# =====================================================================
_calls = {"n": 0, "max_tokens_seen": []}


def _fake_truncated_then_recovers(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source != "state_extractor":
        return "{}"
    _calls["n"] += 1
    _calls["max_tokens_seen"].append(max_tokens)
    if _calls["n"] == 1:
        # Simulates the real live shape: cut off mid-object, a genuine
        # truncation signal from the API itself.
        chat._extractor_call_meta.stop_reason = "max_tokens"
        chat._extractor_call_meta.output_tokens = max_tokens
        return '{"trip_update": {"dates": {"depart'
    chat._extractor_call_meta.stop_reason = "end_turn"
    chat._extractor_call_meta.output_tokens = 180
    return json.dumps({
        "trip_update": {"dates": {"departure": "2027-06-11", "return": "2027-06-15"}},
        "restart_request": False, "restart_evidence": None,
        "dates_evidence": None, "destination_evidence": None,
    })


with patch.object(chat, "_post_claude", side_effect=_fake_truncated_then_recovers):
    _result = chat._extract_trip_update(KEY, MODEL, [], "אפשר לדחות יום?", {})
check("truncation repro: the EXTRACTOR is called exactly twice - the "
      "original attempt plus exactly one retry, never a loop",
      _calls["n"] == 2)
check("truncation repro: max_tokens raised on the retry (2000 -> 3500), "
      "both above the old 900 budget that caused the live failures",
      _calls["max_tokens_seen"] == [2000, 3500])
check("truncation repro: the retry recovers the real parsed trip_update "
      "the first, truncated attempt discarded entirely",
      _result[0].get("dates", {}).get("departure") == "2027-06-11")
check("truncation repro: extractor_parse_error is False after the "
      "successful retry",
      _result[-2] is False)
check("truncation repro: extractor_diag correctly reflects the RETRY's own "
      "stop_reason/output_tokens (the attempt that actually succeeded), "
      "and retried=True",
      _result[-1]["stop_reason"] == "end_turn"
      and _result[-1]["output_tokens"] == 180
      and _result[-1]["retried"] is True)

# Regression: a genuinely malformed (non-truncated) response must never
# trigger a wasted retry - a bigger budget would not fix it anyway.
_calls2 = {"n": 0}


def _fake_malformed_not_truncated(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source != "state_extractor":
        return "{}"
    _calls2["n"] += 1
    chat._extractor_call_meta.stop_reason = "end_turn"
    chat._extractor_call_meta.output_tokens = 40
    return "this is not json at all"


with patch.object(chat, "_post_claude", side_effect=_fake_malformed_not_truncated):
    _result_malformed = chat._extract_trip_update(KEY, MODEL, [], "שלום", {})
check("regression: a malformed-but-not-truncated response (stop_reason="
      "end_turn) is called exactly once - no wasted retry",
      _calls2["n"] == 1)
check("regression: extractor_parse_error is still True (genuinely "
      "unparseable), and retried is False",
      _result_malformed[-2] is True and _result_malformed[-1]["retried"] is False)

# Regression: truncation on BOTH attempts still caps at exactly 2 calls -
# never a second retry, never a loop.
_calls3 = {"n": 0}


def _fake_truncated_twice(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source != "state_extractor":
        return "{}"
    _calls3["n"] += 1
    chat._extractor_call_meta.stop_reason = "max_tokens"
    chat._extractor_call_meta.output_tokens = max_tokens
    return '{"trip_update": {"dates": {"depart'


with patch.object(chat, "_post_claude", side_effect=_fake_truncated_twice):
    _result_twice = chat._extract_trip_update(KEY, MODEL, [], "שלום", {})
check("regression: even truncated on BOTH attempts, the EXTRACTOR is "
      "called exactly twice - never more, no infinite loop",
      _calls3["n"] == 2)
check("regression: extractor_parse_error stays True when the retry also "
      "truncates, and retried is still True (the retry DID happen, it "
      "just didn't help this time)",
      _result_twice[-2] is True and _result_twice[-1]["retried"] is True)


# =====================================================================
# End-to-end: a real post-summary shift request whose first EXTRACTOR
# call truncates exactly like the live zd1/zd6/zd7 shape, through a full
# chat_clean() round trip via whatsapp_bridge.ariella_turn.
# =====================================================================
m_trunc = _make_member("qa-run9-extractor-truncation@example.com")
post_summary_state = {
    "destination": {"places": ["טורינו"], "mode": "specific", "status": "known"},
    "destination_airports": ["TRN"],
    "travelers": {"adults": 2},
    "dates": {"departure": "2027-06-10", "return": "2027-06-14", "needs_confirmation": False, "candidate_ranges": []},
    "requested_services": ["flights"],
    "session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
    "active_session": None,
    "ready_for_summary": True,
    "trip_type": "regular",
    "departure_airport": "TLV",
    "budget_per_person": {"amount": 2000, "currency": "ILS"},
    "flight": {"baggage": ["checked_bag"], "connection_preference": "no_preference"},
}
database.save_ariella_conversation(m_trunc, [
    {"role": "user", "content": "טורינו, 10-14 ביוני 2027, זוג, מזוודה"},
    {"role": "assistant", "content": "מאשרת שהכל סגור! חופשה נעימה! טורינו, 10-14 ביוני 2027."},
], dict(post_summary_state))

_e2e_calls = {"n": 0}


def _fake_e2e_truncated(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        _e2e_calls["n"] += 1
        if _e2e_calls["n"] == 1:
            chat._extractor_call_meta.stop_reason = "max_tokens"
            chat._extractor_call_meta.output_tokens = max_tokens
            return '{"trip_update": {}, "restart_request": false, "rest'
        chat._extractor_call_meta.stop_reason = "end_turn"
        chat._extractor_call_meta.output_tokens = 200
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None,
            "relative_date_hint": {
                "weekday_start": None, "weekday_end": None, "month_name": None, "month_relative": None,
                "part_of_month": None, "duration_days": None, "shift_days": 1,
            },
            "relative_date_hint_evidence": "אפשר לדחות את הטיסה ביום אחד?",
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "בטח, מצאתי אפשרות חדשה: " + chat._DATE_OPTIONS_PLACEHOLDER + " מתאים?"
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_e2e_truncated):
    reply = whatsapp_bridge.ariella_turn(m_trunc, "אפשר לדחות את הטיסה ביום אחד?")
state_after = (database.load_ariella_conversation(m_trunc) or {}).get("trip_state") or {}
check("end-to-end: exactly 2 EXTRACTOR calls this turn (the live-shaped "
      "truncation, then the recovering retry)",
      _e2e_calls["n"] == 2)
check("end-to-end: the shift candidate the first, truncated attempt would "
      "have discarded is correctly created and saved after the retry "
      "recovers it",
      bool((state_after.get("dates") or {}).get("candidate_ranges"))
      and (state_after.get("dates") or {}).get("needs_confirmation") is True)
check("end-to-end: the final reply shows the real candidate date "
      "(placeholder rendered) - exactly the zd1/zd6/zd7 request that was "
      "previously silently dropped",
      "11.06.2027" in reply)

_row = _latest_row(m_trunc)
check("end-to-end: a dates_pipeline diagnostic row was written",
      _row is not None)
if _row is not None:
    _details = json.loads(_row["details"])
    _extractor_section = _details.get("extractor") or {}
    check("end-to-end: the diagnostic row's stop_reason reflects the "
          "RETRY's own outcome (end_turn) and retried_on_truncation is True",
          _extractor_section.get("stop_reason") == "end_turn"
          and _extractor_section.get("retried_on_truncation") is True)
    check("end-to-end: output_tokens/starts_with_brace/ends_with_brace are "
          "present and structured (numbers/booleans only)",
          isinstance(_extractor_section.get("output_tokens"), int)
          and isinstance(_extractor_section.get("starts_with_brace"), bool)
          and isinstance(_extractor_section.get("ends_with_brace"), bool))
    check("end-to-end: no customer message text anywhere in the diagnostic "
          "row's details",
          "אפשר לדחות את הטיסה ביום אחד?" not in _row["details"])


if FAILED:
    print(f"\n{len(FAILED)} CHECK(S) FAILED:")
    for name in FAILED:
        print(f"  - {name}")
    sys.exit(1)
print("\nALL RUN-9 EXTRACTOR-TRUNCATION-FIX TESTS PASSED")
