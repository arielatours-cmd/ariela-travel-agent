"""QA for Shaked's stage-3 run-3 finding (18.10.2026, main 4db4653, qa/
reports/2026-10-18-stage3-run3.md, branch shaked @80d27f8), scenario V3
(Berlin) - a genuine production loop: after the customer declined the car
("לא"), with every domain (flights/lodging/car/trip_planning) now complete
or declined, the guided-extraction dispatcher kept producing a lodging
question ("באיזה אזור תרצו שהלינה תהיה?") 10 times in a row, even though
the customer's answer ("מיטה") was already reflected in state
(lodging.details.locations). guided.current_question stayed stuck at
"lodging_type" with attempts climbing to 10 the whole time.

This is task 1 of Shlomo's two-part follow-up (urgent, small, separate PR -
the deeper current_question/asked-text mismatch, task 2, is its own larger
PR): once every domain is genuinely decided, the guided dispatcher must
never be consulted again at all - there is nothing left to guide, and the
only correct reply from here on is the final summary. Fixed in
_chat_clean_impl: a state-based gate (every domain complete/declined) now
skips calling _handle_guided_extraction_turn entirely, mirroring the exact
check _final_summary_fallback_text/the missing-final-summary retry already
use for "is this trip actually all decided".

Builds state through the real /api/ariella/chat-clean route (never a
hand-built fixture bypassing the real code), per Shlomo's own testing rule
from the #81 review round.

Run: python3 tools/qa_stage3_run3_guided_loop_guard.py
"""
import os
import sys
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
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA Guided Loop Guard", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def _post(message, history, trip_state, member_id):
    with client.session_transaction() as sess:
        sess["member_id"] = member_id
    r = client.post("/api/ariella/chat-clean", json={
        "message": message, "history": history, "trip_state": trip_state,
    })
    return r.get_json()


os.environ["GUIDED_EXTRACTION_STEPS"] = "dates,travelers,baggage,lodging"

# =====================================================================
# Unit level: the gate itself never calls the guided dispatcher once every
# domain is decided, whatever its own internal bookkeeping still thinks.
# =====================================================================
BERLIN_ALL_DECIDED = {
    "destination": {"places": ["ברלין"], "mode": "specific", "status": "known"},
    "active_session": None,
    "requested_services": ["flights", "lodging", "car", "trip_planning"],
    "session_status": {"flights": "complete", "lodging": "complete", "car": "declined", "trip_planning": "complete"},
    "dates": {"departure": "2026-11-10", "return": "2026-11-13"},
    "travelers": {"adults": 1},
    "lodging": {"details": {"locations": "מיטה, ברלין"}},
    "guided": {"current_question": "lodging_type", "attempts": 10,
               "answered": ["dates", "travelers", "baggage"]},
}

with patch.object(chat, "_handle_guided_extraction_turn") as mock_guided:
    member1 = _make_member("qa-s3x3-berlin-gate@example.com")
    with patch.object(chat, "_post_claude", side_effect=lambda *a, **kw: (
            "{}" if kw.get("source") == "state_extractor" else "מצוין, החופשה שלכם מוכנה. אם הכול נכון, כתבי מאשרת."
    )):
        r1 = _post("מיטה", [], dict(BERLIN_ALL_DECIDED), member1)
    check("Berlin repro: once every domain is complete/declined, the guided "
          "dispatcher is never even called this turn - the exact gate that "
          "stops the loop",
          not mock_guided.called)

# =====================================================================
# Full integration: the same state through the real route - no guided
# hint is produced, guided state is left untouched (never re-engaged),
# and the turn falls through to ordinary processing instead of looping.
# =====================================================================
member2 = _make_member("qa-s3x3-berlin-e2e@example.com")
with patch.object(chat, "_post_claude", side_effect=lambda *a, **kw: (
        "{}" if kw.get("source") == "state_extractor" else "מצוין, החופשה שלכם מוכנה. אם הכול נכון, כתבי מאשרת."
)):
    r2 = _post("מיטה", [], dict(BERLIN_ALL_DECIDED), member2)
tu2 = r2.get("trip_update") or {}
check("Berlin repro end-to-end: no guided ask-hint is produced once every "
      "domain is already decided",
      not tu2.get("_guided_ask_hint"))
check("Berlin repro end-to-end: guided.attempts never climbs further (the "
      "dispatcher was skipped, not merely failed quietly)",
      (tu2.get("guided") or BERLIN_ALL_DECIDED["guided"]).get("attempts", 10) <= 10)
check("Berlin repro end-to-end: the reply is NOT a re-ask of the lodging "
      "area/type question - the loop is broken",
      "אזור" not in str(r2.get("reply") or "") and "סוג לינה" not in str(r2.get("reply") or ""))

# =====================================================================
# Regression: the gate must never fire while a domain is still genuinely
# open - guided keeps working normally for an ordinary, not-yet-closed
# trip (the gate is specific to "everything already decided", not a
# blanket kill-switch).
# =====================================================================
member3 = _make_member("qa-s3x3-not-all-decided@example.com")
OPEN_LODGING_STATE = {
    "destination": {"places": ["רומא"], "mode": "specific", "status": "known"},
    "active_session": "lodging",
    "requested_services": ["flights", "lodging"],
    "session_status": {"flights": "complete", "lodging": "active", "car": "pending", "trip_planning": "pending"},
    "dates": {"departure": "2026-11-10", "return": "2026-11-15"},
    "travelers": {"adults": 2},
}
# Scoped to "lodging" only (not "baggage,lodging") so this check isolates
# the thing it's actually testing - whether the new all-domains-decided
# gate wrongly suppresses guided when real domains remain open - without
# baggage separately competing for the same current_question slot.
os.environ["GUIDED_EXTRACTION_STEPS"] = "lodging"
with patch.object(chat, "_post_claude", side_effect=lambda *a, **kw: (
        "{}" if kw.get("source") == "state_extractor" else "תשובה לדוגמה."
)):
    r3 = _post("בואו נסגור את הלינה", [], dict(OPEN_LODGING_STATE), member3)
os.environ["GUIDED_EXTRACTION_STEPS"] = "dates,travelers,baggage,lodging"
tu3 = r3.get("trip_update") or {}
check("regression: guided still proactively engages normally when real "
      "domains remain open (lodging requested, nothing decided yet)",
      (tu3.get("guided") or {}).get("current_question") == "lodging_type"
      and "סוג לינה" in str(tu3.get("_guided_ask_hint") or ""))

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE email IN (?, ?, ?)",
                 ("qa-s3x3-berlin-gate@example.com", "qa-s3x3-berlin-e2e@example.com",
                  "qa-s3x3-not-all-decided@example.com"))
    conn.commit()

os.environ.pop("GUIDED_EXTRACTION_STEPS", None)

if FAILED:
    print(f"\nFAILED ({len(FAILED)}): {FAILED}")
    sys.exit(1)
print("\nALL STAGE-3 RUN-3 GUIDED-LOOP-GUARD TESTS PASSED")
