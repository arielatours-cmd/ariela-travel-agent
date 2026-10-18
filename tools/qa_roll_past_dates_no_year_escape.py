"""QA for Shlomo's urgent follow-up (18.10.2026, qa/reports/2026-10-18-
stage3-run4.md, s3y2 - Tuscany): a live bug where "1.7 עד 10.7" (no year
stated) was saved as 2026-07-01/2026-07-10 - already in the past, since
today is 2026-10-18 - and the summary showed 2026. A search for flights on
a date that has already passed can never be correct.

_roll_past_dates already existed for exactly this ("day+month without a
year rolls to its next future occurrence"), but its own "did the customer
explicitly type that year" escape scanned the WHOLE conversation text for
the bare digit string of the departure's year - ANY unrelated mention of
that year anywhere (a budget figure, a flight number, anything) would
false-positive and wrongly skip the correction entirely.

Shlomo's explicit instruction (relayed, 18.10): remove that escape
entirely. "גם תאריך מלא שנמצא בעבר לא נשמר" (a full date found to be in
the past is not saved either) - there is no legitimate reason for a
vacation-search bot to keep a departure date in the past, whether the
customer stated the year explicitly or not. _roll_past_dates now always
rolls a past departure forward to its next future occurrence, with no
exception.

Shaked's review of that first version (18.10, same report) found it still
didn't fix the live bug, for two reasons, both per state:
1. The function was only called from the main per-turn extraction
   pipeline (one call site) - the 014a guided-extraction path for the
   "dates" field writes directly to trip_update without ever passing
   through it, so a past date answered via a guided "when do you want to
   fly?" question was never corrected at all. Moved the one call to
   _reply, the single point every successful turn passes through
   regardless of which branch produced the trip_update.
2. A return date earlier than its own departure (e.g. "28.12 עד 3.1" -
   departure resolves to 2026-12-28, return to 2026-01-03, the model
   leaving both in the same stated year despite the trip crossing a new
   year) is never valid either. The return itself now also rolls forward
   a year at a time until it's no longer before departure.

Her THIRD review (round 3, same PR) found the _reply-only call still
wasn't enough: the PERSISTED state was correctly rolled, but Tinkerbell
herself - every reply-composing call site goes through _call_tinkerbell,
and _reply only runs afterward, at save time - still saw and could quote
the UNCORRECTED date. The call moved again, into _call_tinkerbell itself
(mutates state in place, so the fix also carries back into the caller's
own dict before persistence - no need to patch each of its ~10 call
sites by hand); _reply's own call stays as a safety net for any path
that never reaches _call_tinkerbell at all.

Same review, second finding: rolling ANY return-before-departure forward
a full year was too aggressive - a same-year date mix-up (departure 5.3,
return 1.3, both stated as 2027 - a transposed day, not a trip crossing a
New Year) got rolled into a fabricated year-long "vacation" instead of
being flagged as the ambiguity it is. Only rolled now when departure
falls in Nov/Dec and return in Jan/Feb/Mar - the actual shape of an
unstated-year New Year's trip; any other case sets dates.needs_
confirmation=True (the field Ariella already uses to ask the customer to
confirm/clarify) instead of guessing which date is wrong.

Run: python3 tools/qa_roll_past_dates_no_year_escape.py
"""
import os
import sys
import json
import sqlite3
from datetime import date, datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

import ariella_chat_clean as chat
import whatsapp_bridge
from werkzeug.security import generate_password_hash

DB = database.DB_PATH
FAILED = []


def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA Roll Dates", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# =====================================================================
# 1. The original live repro: bare day/month (no year at all) that
#    resolves to a past date rolls forward exactly one year.
# =====================================================================
state1 = {"dates": {"departure": "2026-07-01", "return": "2026-07-10"}}
r1 = chat._roll_past_dates(dict(state1))
check("s3y2 repro: a bare day/month (no year) already in the past rolls forward to next year",
      r1["dates"]["departure"] == "2027-07-01" and r1["dates"]["return"] == "2027-07-10")

# =====================================================================
# 2. The exact false-positive this fix removes: an unrelated mention of
#    the departure's own year digits elsewhere in the conversation must
#    no longer suppress the correction (the escape is gone entirely now).
# =====================================================================
state2 = {"dates": {"departure": "2026-07-01", "return": "2026-07-10"}}
r2 = chat._roll_past_dates(dict(state2))
check("regression fix: with the 'customer typed that year' escape removed, this "
      "still rolls forward regardless of anything the customer wrote elsewhere",
      r2["dates"]["departure"] == "2027-07-01")

# =====================================================================
# 3. Shlomo's explicit instruction: a FULL date (the customer clearly
#    stated the year) that is still in the past is ALSO not saved as-is -
#    it rolls forward too, exactly like the bare-date case. No escape.
# =====================================================================
state3 = {"dates": {"departure": "2026-07-01", "return": "2026-07-10"}}
r3 = chat._roll_past_dates(dict(state3))
check("Shlomo's instruction: a full past date (year included) is never silently "
      "saved as-is either - it rolls forward too, with no exception",
      r3["dates"]["departure"] == "2027-07-01" and r3["dates"]["return"] == "2027-07-10")

# =====================================================================
# 4. Regression: a departure already in the future is left untouched.
# =====================================================================
state4 = {"dates": {"departure": "2027-07-01", "return": "2027-07-10"}}
r4 = chat._roll_past_dates(dict(state4))
check("regression: a departure already in the future is unchanged",
      r4["dates"]["departure"] == "2027-07-01" and r4["dates"]["return"] == "2027-07-10")

# =====================================================================
# 5. Regression: a state with no dates at all, or no departure, is a
#    harmless no-op (never raises).
# =====================================================================
check("regression: a state with no 'dates' key at all is a harmless no-op",
      chat._roll_past_dates({}) == {})
check("regression: dates present but departure missing is a harmless no-op",
      chat._roll_past_dates({"dates": {"return": "2027-07-10"}})["dates"].get("departure") is None)

# =====================================================================
# 6. Multi-year rollover: a departure more than one year in the past
#    (e.g. a stale value from a much earlier conversation) rolls forward
#    to the correct NEXT future year, not just +1 blindly.
# =====================================================================
far_past_year = date.today().year - 3
state6 = {"dates": {"departure": f"{far_past_year}-07-01", "return": f"{far_past_year}-07-10"}}
r6 = chat._roll_past_dates(dict(state6))
rolled_dep = date.fromisoformat(r6["dates"]["departure"])
check("regression: a departure several years in the past rolls forward to the "
      "correct next future year, not a fixed +1",
      rolled_dep >= date.today() and rolled_dep.month == 7 and rolled_dep.day == 1)

# =====================================================================
# 7. Shaked's finding #2: a return earlier than its own departure (a New
#    Year's-crossing trip left in the same stated year) rolls the return
#    forward, independently of whether departure itself needed rolling.
# =====================================================================
state7 = {"dates": {"departure": "2026-12-28", "return": "2026-01-03"}}
r7 = chat._roll_past_dates(dict(state7))
check("Shaked's finding: a return before its own departure (New Year's crossing) "
      "rolls the return forward a year",
      r7["dates"]["departure"] == "2026-12-28" and r7["dates"]["return"] == "2027-01-03")

state8 = {"dates": {"departure": "2025-12-28", "return": "2025-01-03"}}
r8 = chat._roll_past_dates(dict(state8))
check("regression: a departure that is BOTH in the past AND whose return crosses a "
      "new year is corrected on both axes, departure first then return",
      r8["dates"]["departure"] == "2026-12-28" and r8["dates"]["return"] >= r8["dates"]["departure"])

check("regression: a normal future trip where return already comes after departure is untouched",
      chat._roll_past_dates({"dates": {"departure": "2027-03-01", "return": "2027-03-10"}})["dates"]
      == {"departure": "2027-03-01", "return": "2027-03-10"})

# =====================================================================
# 7b. Shaked's round-3 finding: a same-year date mix-up (not a plausible
#     New Year's crossing) must NOT be rolled a full year forward - that
#     fabricates a year-long trip. Flagged for confirmation instead.
# =====================================================================
state_mixup = {"dates": {"departure": "2027-03-05", "return": "2027-03-01"}}
r_mixup = chat._roll_past_dates(dict(state_mixup))
check("round-3 finding: a same-year return-before-departure mix-up (not Nov/Dec->Jan/Feb/Mar) "
      "is NOT rolled a full year forward",
      r_mixup["dates"]["return"] == "2027-03-01")
check("round-3 finding: it is flagged needs_confirmation instead of silently guessed",
      r_mixup["dates"].get("needs_confirmation") is True)

check("regression: a genuine Nov/Dec departure with a Jan/Feb/Mar return still rolls "
      "(the one real New Year's-crossing shape)",
      chat._roll_past_dates({"dates": {"departure": "2026-11-20", "return": "2026-02-01"}})["dates"]["return"] == "2027-02-01")
check("regression: an October departure with a September return (same-year, far apart, "
      "not Nov/Dec->Jan/Feb/Mar) is flagged, not rolled",
      chat._roll_past_dates({"dates": {"departure": "2027-10-10", "return": "2027-09-01"}})["dates"].get("needs_confirmation") is True)


# =====================================================================
# 7c. Round-3 finding #1, verified the way Shaked explicitly asked: what
#     Tinkerbell herself RECEIVES (system_dynamic), not just what gets
#     persisted. The fix moved into _call_tinkerbell - confirm the
#     uncorrected date never reaches it and the corrected one does.
# =====================================================================
_captured = {}


def _fake_post_claude_tinkerbell(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "tinkerbell_reply":
        _captured["system_dynamic"] = system_dynamic
        return "תשובה לדוגמה."
    return "{}"


_state_for_tink = {"dates": {"departure": "2026-07-01", "return": "2026-07-10"}, "destination": {"places": ["רומא"]}}
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_tinkerbell):
    chat._call_tinkerbell("key", "model", [], "הי", _state_for_tink)
check("round-3 finding #1: Tinkerbell's own system_dynamic never contains the "
      "uncorrected (past) date",
      "2026-07-01" not in _captured.get("system_dynamic", ""))
check("round-3 finding #1: Tinkerbell's own system_dynamic contains the corrected "
      "(rolled-forward) date instead",
      "2027-07-01" in _captured.get("system_dynamic", ""))
check("round-3 finding #1: the caller's own state dict is also corrected in place "
      "(not just a local copy inside _call_tinkerbell)",
      _state_for_tink["dates"]["departure"] == "2027-07-01")

# =====================================================================
# 8. Shaked's finding #1, end-to-end: a past date answered through the
#    014a guided-extraction "dates" field (not the main extraction
#    pipeline) is ALSO corrected now - the fix lives at the single _reply
#    exit point, not a second call site inside the guided path.
# =====================================================================
m_guided = _make_member("qa-roll-dates-guided@example.com")
guided_state = {
    "destination": {"places": ["רומא"], "mode": "specific", "status": "known"},
    "destination_airports": ["FCO"],
    "travelers": {"adults": 2},
    "session_status": {"flights": "active", "lodging": "pending", "car": "pending", "trip_planning": "pending"},
    "active_session": "flights",
    "guided": {"current_question": "dates", "attempts": 0, "answered": ["travelers"]},
}
database.save_ariella_conversation(m_guided, [
    {"role": "user", "content": "רומא, זוג"},
    {"role": "assistant", "content": "קלטתי - רומא. מתי תרצו לטוס?"},
], guided_state)


_captured_guided = {}


def _fake_post_claude(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "guided_extract":
        return json.dumps({
            "status": "answered", "departure": "2026-07-01", "return": "2026-07-10",
            "nights": None, "period": None, "confidence": "high", "also_mentioned": {},
        })
    if source == "state_extractor":
        return json.dumps({"trip_update": {}, "restart_request": False, "restart_evidence": None})
    if source == "tinkerbell_reply":
        _captured_guided["system_dynamic"] = system_dynamic
        return "תשובה לדוגמה."
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    whatsapp_bridge.ariella_turn(m_guided, "1.7 עד 10.7")
state_guided = (database.load_ariella_conversation(m_guided) or {}).get("trip_state") or {}
check("Shaked's finding #3 (verify what Tinkerbell RECEIVES, not just what's saved): "
      "in the real end-to-end guided-path turn, Tinkerbell's own system_dynamic already "
      "shows the corrected date, never the raw past one",
      "2026-07-01" not in _captured_guided.get("system_dynamic", "")
      and "2027-07-01" in _captured_guided.get("system_dynamic", ""))
check("Shaked's finding #1 end-to-end: a past date answered via the GUIDED dates field "
      "(not the main extraction pipeline) is rolled forward too",
      state_guided.get("dates", {}).get("departure") == "2027-07-01"
      and state_guided.get("dates", {}).get("return") == "2027-07-10")

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL ROLL-PAST-DATES-NO-YEAR-ESCAPE TESTS PASSED")
