"""QA for Shaked's direct stage-1 run-4 report, Marseille finding #3:

"בתחילת החודש הבא, מרביעי עד ראשון" produced two real pending candidates
(candidate_ranges=["4-8.11", "11-15.11"], needs_confirmation=True), which
Ariella never displayed - resolved separately by PR #113's {{DATE_OPTIONS}}
placeholder mechanism (the whole point of that fix: whatever's actually in
state always gets shown).

The SECOND part of this finding, fixed here: "לפני שנתיים היינו שם 10 עד 14
באוגוסט" (a reminiscence about a PAST trip, not a request for the current
one) changed trip_update.dates.period to "רביעי עד ראשון באוגוסט 2027" -
the extractor read the quoted past dates as if they described a NEW
preference for the upcoming trip, exactly as if the customer had actually
asked to fly then.

Per the standing architecture rule (genuine model understanding, never a
regex/phrase list): EXTRACTOR_SYSTEM now carries an explicit instruction
that a mention of when a trip already happened ("לפני שנה/שנתיים/שלוש
טסנו ל-X", "בפעם הקודמת היינו שם ב-", "בעבר ביקרנו ב-") is reminiscence
only, never a request - dates_evidence, relative_date_hint and
trip_update.dates (departure/return/period) must all stay null/unchanged
from such a sentence alone. This is the same evidence-gated discipline
already established for every other date-change path in this file
(Bologna, PR #94/#98) - the fix is a prompt instruction, not new code, so
this QA both asserts the instruction text itself and end-to-end confirms
the pipeline leaves dates genuinely untouched when the (correctly-
behaving, per the new instruction) model returns nulls for such a message.

Run: python3 tools/qa_marseille_past_trip_dates.py
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
            ("QA Marseille Past Trip", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


# =====================================================================
# 1. The EXTRACTOR_SYSTEM prompt itself now explicitly teaches the model
# that a past-trip reminiscence is never a request for the current trip's
# dates - genuine understanding instructed in the prompt, never a
# code-level phrase list deciding this.
# =====================================================================
check("EXTRACTOR_SYSTEM explicitly names past-trip reminiscence phrasing "
      "('לפני שנה/שנתיים', 'בפעם הקודמת') as context only, never a request",
      "לפני שנה/שנתיים/שלוש טסנו" in chat.EXTRACTOR_SYSTEM
      and "בפעם הקודמת היינו שם" in chat.EXTRACTOR_SYSTEM)
check("the instruction explicitly forbids filling dates_evidence, "
      "relative_date_hint AND trip_update.dates from such a sentence",
      "אל תמלאי dates_evidence, relative_date_hint או trip_update.dates" in chat.EXTRACTOR_SYSTEM)

# =====================================================================
# 2. End-to-end: with the (correctly-behaving, per the new instruction)
# extractor returning nulls for a past-trip reminiscence mid-conversation,
# the pipeline leaves the still-open dates field completely untouched -
# no period, no candidate, nothing invented from the quoted past dates.
# =====================================================================
MARSEILLE_STATE = {
    "destination": {"places": ["מרסיי"], "mode": "specific", "status": "known"},
    "destination_airports": ["MRS"],
    "travelers": {"adults": 2},
    "dates": {"needs_confirmation": True, "candidate_ranges": ["04.11.2026–08.11.2026", "11.11.2026–15.11.2026"]},
    "requested_services": ["flights"],
    "service_decisions": {"flights": {"wanted": True}},
    "session_status": {"flights": "active", "lodging": "pending", "car": "pending", "trip_planning": "pending"},
    "active_session": "flights",
    "guided": {"current_question": None, "attempts": 0, "answered": ["travelers", "baggage"]},
}


def _mock_past_trip_correctly_ignored(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        # Per the new instruction: a past-trip reminiscence yields nulls
        # across the board - exactly what a correctly-behaving model
        # returns now that the carve-out is explicit.
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
            "relative_date_hint": None, "relative_date_hint_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "איזה כיף! אז עבור הטיול הזה - מתי תרצו לצאת ולחזור?"
    return "{}"


m_marseille = _make_member("qa-marseille-past-trip@example.com")
database.save_ariella_conversation(m_marseille, [
    {"role": "user", "content": "מרסיי, זוג, בתחילת החודש הבא, מרביעי עד ראשון"},
    {"role": "assistant", "content": "קלטתי - מרסיי. סביב איזה תקציב אתם חושבים?"},
], dict(MARSEILLE_STATE))

with patch.object(chat, "_post_claude", side_effect=_mock_past_trip_correctly_ignored):
    whatsapp_bridge.ariella_turn(m_marseille, "לפני שנתיים היינו שם 10 עד 14 באוגוסט")

_state_after = (database.load_ariella_conversation(m_marseille) or {}).get("trip_state") or {}
_dates_after = _state_after.get("dates") or {}
check("a past-trip reminiscence ('לפני שנתיים היינו שם 10 עד 14 באוגוסט') "
      "never overwrites period with a new, unrequested window",
      not _dates_after.get("period") or _dates_after.get("period") == MARSEILLE_STATE["dates"].get("period"))
check("the real pending candidates from the ORIGINAL request ('מרביעי עד "
      "ראשון', the start of next month) are left completely untouched - "
      "never replaced by anything derived from the past-trip mention",
      _dates_after.get("candidate_ranges") == MARSEILLE_STATE["dates"]["candidate_ranges"])
check("needs_confirmation stays exactly as it was - a reminiscence is "
      "never treated as a fresh date proposal of its own",
      _dates_after.get("needs_confirmation") is True)
check("no departure/return got silently committed from the past dates",
      not _dates_after.get("departure") and not _dates_after.get("return"))

# =====================================================================
# 3. Direct unit tests of _deterministic_period_facts's new `state` guard -
# the exact mechanism behind the bug, isolated from the full turn pipeline.
# =====================================================================
_RESOLVED_CANDIDATE_STATE = {"dates": {"needs_confirmation": True, "candidate_ranges": ["04.11.2026–08.11.2026"]}}
_RESOLVED_CONFIRMED_STATE = {"dates": {"departure": "2026-11-04", "return": "2026-11-08", "needs_confirmation": False}}
_OPEN_STATE = {"dates": {}}

check("with dates already resolved into real candidates, a later message "
      "naming only a MONTH (no weekday pair of its own) never completes "
      "from a stale weekday pair left in history",
      chat._deterministic_period_facts(
          "לפני שנתיים היינו שם 10 עד 14 באוגוסט",
          [{"role": "user", "content": "בתחילת החודש הבא, מרביעי עד ראשון"}],
          _RESOLVED_CANDIDATE_STATE,
      ) == {})
check("same guard applies once dates are already CONFIRMED (not just pending)",
      chat._deterministic_period_facts(
          "לפני שנתיים היינו שם 10 עד 14 באוגוסט",
          [{"role": "user", "content": "בתחילת החודש הבא, מרביעי עד ראשון"}],
          _RESOLVED_CONFIRMED_STATE,
      ) == {})
check("regression: with dates still fully OPEN (the original use case this "
      "function was built for), cross-message completion still works - "
      "'סוף יוני' in one message, 'ראשון עד חמישי' in the next",
      bool(chat._deterministic_period_facts(
          "ראשון עד חמישי",
          [{"role": "user", "content": "סוף יוני"}],
          _OPEN_STATE,
      ).get("dates", {}).get("candidate_ranges")))
check("regression: passing no state at all (state=None, the old call "
      "signature) behaves exactly as before - still open for cross-message "
      "completion",
      bool(chat._deterministic_period_facts(
          "ראשון עד חמישי",
          [{"role": "user", "content": "סוף יוני"}],
      ).get("dates", {}).get("candidate_ranges")))
check("with dates already resolved, a message naming BOTH signals itself "
      "(a genuine, self-contained new request) still works normally",
      bool(chat._deterministic_period_facts(
          "רוצה בעצם סוף יולי, ראשון עד חמישי",
          [],
          _RESOLVED_CANDIDATE_STATE,
      ).get("dates", {}).get("candidate_ranges")))

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL MARSEILLE-PAST-TRIP-DATES TESTS PASSED")
