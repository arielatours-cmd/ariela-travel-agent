"""QA for Shaked's second new finding while regression-testing live
(trying to reproduce the business owner's Croatia manual test, 16.10.2026):
trip_planning.approved became True at the very start of the conversation,
before any route was ever proposed.

Live sequence: Ariella asked about airports/route-building and the trip
dates/travelers together. The customer answered "כן. זוג +2" (yes, to the
earlier airport/route question; a couple + 2 kids, answering the travelers
question). Ariella's own reply said "מצוין, המסלול מאושר" ("great, the
route is approved") - a hallucination, since no route had been proposed at
all - and the extractor, reading that reply as context, faithfully copied
the claim into trip_planning.approved=True. Once approved was already
True, the REAL day-by-day route (built minutes later and genuinely
accepted) was never recognized as needing approval, and trip_planning.
details.route/pace stayed empty forever - Ariella asked "ספרי לי מה אתם
אוהבים לעשות בחופשה"/"איזה קצב?" in a loop even after the real route had
already been presented and accepted.

Fixed: _guard_premature_route_approval runs right after the extractor
merge and reverts a NEWLY-claimed trip_planning.approved=True (never an
already-approved decision carried over from a previous turn) unless a
real day-by-day route (2+ distinct day markers) genuinely appears
somewhere in the conversation's assistant messages.

Run: python3 tools/qa_premature_route_approval_guard.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import ariella_chat_clean as chat

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


LIVE_HISTORY = [
    {"role": "assistant", "content": "זו חופשה רגילה, נסיעת עסקים, או חופשת סקי?"},
    {"role": "user", "content": "רגילה"},
    {"role": "assistant", "content": "בוא נוודא את התאריכים - 19.9.2027 עד 30.9.2027 - נכון? בינתיים, כמה נוסעים אתם, ויש ילדים בהרכב?"},
]

previous = {"trip_planning": {"interested": True, "details": {}}}
extractor_output = {"trip_planning": {
    "interested": True, "approved": True,
    "approved_text": "בוא נוודא את התאריכים - 19.9.2027 עד 30.9.2027 - נכון?",
    "details": {},
}}
merged = chat._merge_trip_state(previous, extractor_output)
fixed = chat._guard_premature_route_approval(previous, merged, LIVE_HISTORY)

check("exact live repro: premature approved=True is reverted to False",
      fixed["trip_planning"]["approved"] is False)
check("the bogus approved_text is dropped, not left dangling",
      "approved_text" not in fixed["trip_planning"])
check("enrichment_pending is dropped too if it was set alongside the bogus approval",
      "enrichment_pending" not in chat._guard_premature_route_approval(
          previous,
          chat._merge_trip_state(previous, {"trip_planning": {"approved": True, "enrichment_pending": True, "details": {}}}),
          LIVE_HISTORY,
      )["trip_planning"])

# --- Regression: a genuine day-by-day route's approval must never be touched ---
REAL_ROUTE_HISTORY = [
    {"role": "assistant", "content": (
        "יום 1, 1.6.2027 (שלישי)\nנחיתה בזאגרב.\n\n"
        "יום 2, 2.6.2027 (רביעי)\nפלטביצה.\n\nמתאים לך ככה?"
    )},
]
merged_real = chat._merge_trip_state({"trip_planning": {"details": {}}}, {"trip_planning": {"approved": True, "details": {}}})
fixed_real = chat._guard_premature_route_approval({"trip_planning": {"details": {}}}, merged_real, REAL_ROUTE_HISTORY)
check("regression: a genuine day-by-day route's approval survives the guard",
      fixed_real["trip_planning"]["approved"] is True)

# --- Regression: route built incrementally across several turns is still recognized ---
INCREMENTAL_ROUTE_HISTORY = [
    {"role": "assistant", "content": "יום 1, 1.6.2027 (שלישי)\nנחיתה בזאגרב."},
    {"role": "user", "content": "מעולה, תמשיכי"},
    {"role": "assistant", "content": "יום 2, 2.6.2027 (רביעי)\nפלטביצה."},
    {"role": "user", "content": "מתאים, תודה"},
]
merged_incr = chat._merge_trip_state({"trip_planning": {"details": {}}}, {"trip_planning": {"approved": True, "details": {}}})
fixed_incr = chat._guard_premature_route_approval({"trip_planning": {"details": {}}}, merged_incr, INCREMENTAL_ROUTE_HISTORY)
check("regression: a route built up turn-by-turn (day markers split across messages) still counts as real evidence",
      fixed_incr["trip_planning"]["approved"] is True)

# --- Regression: an already-approved route from a PREVIOUS turn must never be reopened ---
already_state = {"trip_planning": {"approved": True, "details": {}}}
merged_already = chat._merge_trip_state(already_state, {"trip_planning": {"approved": True, "details": {}}})
fixed_already = chat._guard_premature_route_approval(already_state, merged_already, [])
check("regression: an already-approved route from a previous turn is never reopened",
      fixed_already["trip_planning"]["approved"] is True)

# --- Regression: no trip_planning / not approved at all -> guard is a no-op ---
no_planning_state = {}
check("regression: no trip_planning key at all -> guard is a safe no-op",
      chat._guard_premature_route_approval({}, dict(no_planning_state), []) == no_planning_state)

# --- Shaked's root-cause finding: _day_mention_count must not count a
# weekday-conflict/date-verification clarification ("יוצא ביום X") as real
# route evidence, since the date isn't always literally adjacent to "יום". ---
check("_day_mention_count excludes 'יוצא ביום X' date-verification phrasing",
      chat._day_mention_count(
          "19.9.2027 יוצא ביום ראשון, אבל 30.9.2027 יוצא ביום רביעי"
      ) == 0)
check("_day_mention_count excludes bare 'יוצא יום X' (no 'ב') too",
      chat._day_mention_count("30.9.2027 יוצא יום רביעי") == 0)
check("_day_mention_count regression: a genuine route built with weekday names still counts",
      chat._day_mention_count("יום ראשון: הגעה לזאגרב. יום שני: פלטביצה.") >= 2)

# --- Shaked's root-cause finding: this guard alone did NOT fix the live
# bug. She reproduced it end-to-end (real chat-clean endpoint, mocked
# extractor returning "{}") and found the actual culprit is the SEPARATE
# deterministic planning_accept gate inside chat_clean() itself, whose own
# inline day_mention_count() wrongly counted "19.9.2027 יוצא ביום ראשון,
# אבל 30.9.2027 יוצא ביום רביעי" (a date-verification/conflict
# clarification Ariella sent along with the dates/travelers question) as
# 2 genuine route-day markers - so "כן. זוג +2" (answering the travelers
# question) satisfied planning_accept's day_mention_count(prior_assistant)
# >= 2 check and got misread as itinerary approval, regardless of this
# guard. Fixed by excluding "יום <weekday>" mentions immediately preceded
# by "יוצא" (with an optional "ב") from BOTH the inline day_mention_count
# in chat_clean() and this module's own _day_mention_count - reproduced
# here through the real endpoint, not just the unit-level guard above,
# per her methodology.
import database
database.init_db()
import app as app_module
from unittest.mock import patch


def _fake_post_claude(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source in ("state_extractor", "classifier"):
        return "{}"
    return "תשובה לדוגמה."


client = app_module.app.test_client()
LIVE_E2E_HISTORY = [
    {"role": "assistant", "content": "זו חופשה רגילה, נסיעת עסקים, או חופשת סקי?"},
    {"role": "user", "content": "רגילה"},
    {"role": "assistant", "content": (
        "19.9.2027 יוצא ביום ראשון, אבל 30.9.2027 יוצא ביום רביעי - "
        "איזה תאריכים בדיוק? ובינתיים, כמה נוסעים אתם, ויש ילדים בהרכב?"
    )},
]
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r_live = client.post("/api/ariella/chat-clean", json={
        "message": "כן. זוג +2",
        "history": LIVE_E2E_HISTORY,
        "trip_state": {"trip_type": "standard", "trip_planning": {"interested": True, "details": {}}},
    })
tu_live = (r_live.get_json() or {}).get("trip_update") or {}
check("e2e exact live repro: 'כן. זוג +2' never gets misread as route approval",
      (tu_live.get("trip_planning") or {}).get("approved") is not True)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL PREMATURE-ROUTE-APPROVAL-GUARD TESTS PASSED")
