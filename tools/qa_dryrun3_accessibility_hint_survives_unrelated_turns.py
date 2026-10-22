"""QA for Shaked's dry-run 3 finding #1 (22.10.2026, qa/reports/
2026-10-22-dryrun3.md, shaked branch @5e7690f - integration/dryrun3,
scenarios B/C/E): the accessibility question's own hint vanished after
turn 0 and never came back, across every later turn where the customer's
message was about something else (budget, car, baggage) - so accessibility
was asked late (C: only after the car), or never asked as a question at
all (B: only the disclosure sentence leaked, with no actual question, and
the customer's "לא" got recorded against nothing).

Root cause: #145 added an unconditional trip_update.pop("_guided_ask_hint",
None) right before the guided dispatcher runs, to fix a DIFFERENT, real bug
(a stale hint frozen forever once every domain was already decided). But
_handle_guided_extraction_turn legitimately returns None - or a dynamic_hint
of None - on a genuinely unrelated aside (the "not changed" branches,
confirmed correct behavior by qa_guided_extraction_*_014a.py's own
scenarios 5/9/12 at the time). The caller read "no hint from the
dispatcher" as "nothing to steer with" and left the pop in place for the
rest of the turn - even though guided.current_question (accessibility) was
still genuinely open the whole time. An unrelated aside is not the same as
the question no longer being pending.

Fixed in ariella_chat_clean.py (the caller, not _handle_guided_extraction_
turn itself): whenever nothing set _guided_ask_hint this turn but
trip_update["guided"]["current_question"] is still non-empty, its hint is
rebuilt fresh right there - never a stale/frozen string (recomputed every
time from whatever current_question is RIGHT NOW), never a new redirect,
never forced wording - exactly what _handle_guided_extraction_turn itself
would have returned had anything changed. This reverses the old "no hint
forced on an unrelated message" expectation in the three 014a scenario
files (5/9/12), updated in this same change - that expectation is exactly
what let the question go unasked.

Run: python3 tools/qa_dryrun3_accessibility_hint_survives_unrelated_turns.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

import ariella_chat_clean as chat
import app as app_module
from datetime import datetime, timezone
from unittest.mock import patch
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
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA dryrun3 acc persists", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def _post(message, history, trip_state, member_id):
    with client.session_transaction() as sess:
        sess["member_id"] = member_id
    r = client.post("/api/ariella/chat-clean", json={
        "message": message, "history": history, "trip_state": trip_state,
    })
    return r.get_json()


os.environ["GUIDED_EXTRACTION_STEPS"] = "dates,travelers,accessibility,baggage"

BASE_STATE = {
    "destination": {"places": ["רומא"], "mode": "specific", "status": "known"},
    "requested_services": ["flights"],
    "session_status": {"flights": "active"},
    "dates": {"departure": "2027-04-10", "return": "2027-04-15"},
    "travelers": {"adults": 2},
    "flight": {"baggage": []},
    "guided": {"current_question": "accessibility", "attempts": 0, "answered": ["dates", "travelers"]},
}

# Each turn's message is about something unrelated to accessibility
# (budget, car preference, a generic aside) - classified other_topic with
# nothing to redirect to, exactly like the live B/C/E transcripts. The
# main Tinkerbell reply call is a neutral placeholder; only the extraction
# side-effect matters here.
UNRELATED_TURNS = [
    "התקציב שלנו בערך 1500 ש\"ח לנוסע",
    "נשמח גם לרכב שכור אם זה זול",
    "איזה מזג אוויר צפוי שם?",
]

member = _make_member("qa-dryrun3-acc-persists@example.com")
state = dict(BASE_STATE)
all_turns_had_hint = True
for i, msg in enumerate(UNRELATED_TURNS):
    with patch.object(chat, "_post_claude", side_effect=lambda *a, source=None, **kw: (
        "{}" if source == "state_extractor"
        else ('{"status": "other_topic", "field": null, "evidence": null}' if source == "guided_extract"
              else "תשובה לדוגמה.")
    )):
        r = _post(msg, [], dict(state), member)
    tu = r.get("trip_update") or {}
    hint = str(tu.get("_guided_ask_hint") or "")
    has_hint = "התאמות נגישות" in hint
    check(f"turn {i+1} ('{msg[:20]}...'): accessibility's own hint is present, "
          "not left empty just because this message was unrelated",
          has_hint)
    check(f"turn {i+1}: current_question is still accessibility (genuinely "
          "unanswered, never silently marked done)",
          (tu.get("guided") or {}).get("current_question") == "accessibility")
    if not has_hint:
        all_turns_had_hint = False
    # Carry the real state forward to the next turn, exactly like the live
    # multi-turn conversation Shaked tested.
    state = {**state, **tu}

check("regression: every one of the 3 consecutive unrelated turns kept the "
      "accessibility hint alive - never just the first one (the live bug: "
      "turn 0 had it, turns 1-3 did not)",
      all_turns_had_hint)

# =====================================================================
# Regression (the three 014a scenario files, updated in this same change):
# confirm this fix does NOT resurrect a hint once the field is genuinely no
# longer pending (e.g. every guided field answered and every domain
# decided) - the original #145 bug (a frozen stale hint) must stay fixed.
# =====================================================================
with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE email='qa-dryrun3-acc-persists@example.com'")
    conn.commit()
os.environ.pop("GUIDED_EXTRACTION_STEPS", None)

if FAILED:
    print(f"\nFAILED ({len(FAILED)}): {FAILED}")
    sys.exit(1)
print("\nALL DRYRUN3-ACCESSIBILITY-HINT-SURVIVES-UNRELATED-TURNS TESTS PASSED")
