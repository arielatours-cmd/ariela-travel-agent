"""QA for Shaked/Shlomo's dry-run 2 finding #2 (22.10.2026, qa/reports/
2026-10-22-dryrun2.md, case A): after the final summary, a customer's
post-summary date-shift request ("let's move it one day forward") got a
reply that omitted {{DATE_OPTIONS}} entirely and just said "checked it for
you" - the shift candidate was computed correctly in state, but Tinkerbell
never actually asked about it.

Root cause: _guided_ask_hint is only ever set OR CLEARED from inside "if
guided_steps and not _all_domains_already_decided:" in _chat_clean_impl.
Its one-turn siblings (_baggage_note_hint, _dates_changed_hint, _shift_
candidate_hint) are each explicitly popped every turn their own condition
doesn't hold - but once _all_domains_already_decided flips to True (every
domain, accessibility included per #143, genuinely resolved), that whole
block is skipped and _guided_ask_hint is never touched again, EVER - it
freezes at whatever it last said (an old baggage/accessibility-turn hint,
seen live) and keeps re-injecting itself into every later, completely
unrelated turn, carrying its own "this is the only thing to ask - it
overrides every other open topic" framing. A genuinely live _shift_
candidate_hint on a later turn loses that unwritten contest to a stale
hint about a question that was already answered turns ago.

Fix: unconditional pop of _guided_ask_hint as the very first thing in that
block (mirroring the sibling pattern exactly), before the conditional
re-set - so it can never survive past the one turn that actually produced
it, regardless of which path (or none) runs after.

Run: python3 tools/qa_dryrun2_stale_guided_hint.py
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
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA dryrun2 stale hint", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
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
# Direct unit coverage: _all_domains_already_decided's own definition is
# unaffected by this fix (it doesn't touch that computation at all) - this
# just documents the state shape case A reaches once every domain,
# accessibility included, is genuinely resolved.
# =====================================================================
_ALL_DECIDED_ACC_RESOLVED = {
    "destination": {"places": ["ג'נובה"], "mode": "specific", "status": "known"},
    "active_session": None,
    "requested_services": ["flights"],
    "session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
    "dates": {"departure": "2027-05-10", "return": "2027-05-15"},
    "travelers": {"adults": 2},
    "flight": {"baggage": ["checked_bag"]},
    "trip_type": "leisure",
    "departure_airport": "TLV",
    "budget_per_person": 500,
    "accessibility": {"needed": False},
    "guided": {"current_question": None, "answered": ["dates", "travelers", "baggage", "accessibility"], "mixed_baggage_pending": False},
    "next_session": None,
    # The bug: a STALE hint left over from several turns ago (e.g. the
    # baggage question, per Shlomo's exact description of the live
    # symptom), still sitting in persisted state from before every domain
    # became decided.
    "_guided_ask_hint": "הפרט הבא לברר: שאלת כבודה ישנה שכבר נענתה מזמן",
    "final_summary_shown": True,
}


def _fake_shift_turn(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
            "relative_date_hint": {
                "weekday_start": None, "weekday_end": None, "month_name": None,
                "month_relative": None, "part_of_month": None, "duration_days": None, "shift_days": 1,
            },
            "relative_date_hint_evidence": "יום אחד קדימה",
            "link_request": False, "link_request_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "classifier":
        return "false"
    if source == "tinkerbell_reply":
        return "בדקתי בשביל - רק רגע לפני שממשיכים."
    return "{}"


member_a = _make_member("qa-dryrun2-stale-hint@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_shift_turn):
    r_a = _post(
        "אפשר להזיז את זה יום אחד קדימה?",
        [{"role": "assistant", "content": "סיכום החופשה... אם כל הפרטים נכונים, כתבי מאשרת."}],
        dict(_ALL_DECIDED_ACC_RESOLVED), member_a,
    )
tu_a = r_a.get("trip_update") or {}
check("FIX: the stale _guided_ask_hint (from a long-resolved baggage "
      "question) never reaches this turn's trip_update once every domain "
      "is genuinely decided - it is unconditionally cleared, not left to "
      "linger forever",
      not tu_a.get("_guided_ask_hint"))
check("the genuinely live _shift_candidate_hint for THIS turn's request "
      "is present and uncontested by the stale hint",
      "_shift_candidate_hint" in tu_a and bool(tu_a.get("_shift_candidate_hint")))
check("the shift candidate itself was actually computed into dates "
      "(needs_confirmation + a real candidate range)",
      bool((tu_a.get("dates") or {}).get("needs_confirmation"))
      and bool((tu_a.get("dates") or {}).get("candidate_ranges")))

# =====================================================================
# Regression: a GENUINELY live guided question (dates+travelers both
# arriving in THIS message, exactly the run-11/#143 Bari shape - current_
# question genuinely advances to accessibility same turn, changed=True)
# must still produce its hint normally - the unconditional pop must never
# suppress a real, freshly-computed guided hint, only a stale leftover
# from a turn that's already over.
# =====================================================================
def _fake_fresh_turn(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {
                "destination": {"places": ["בארי"], "mode": "specific", "status": "known"},
                "dates": {"departure": "2027-04-10", "return": "2027-04-15"},
                "travelers": {"adults": 2},
            },
            "restart_request": False, "restart_evidence": None,
            "dates_evidence": "ה-10 עד ה-15 באפריל", "destination_evidence": "בארי", "trip_type_evidence": None,
            "link_request": False, "link_request_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "classifier":
        return "false"
    if source == "tinkerbell_reply":
        return "קלטתי, בארי בין ה-10 ל-15 באפריל, שני מבוגרים. מה התקציב לאדם לטיסה?"
    return "{}"


member_b = _make_member("qa-dryrun2-still-open@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_fresh_turn):
    state_fresh = {
        "destination": {"places": [], "mode": None, "status": "unknown"},
        "active_session": None, "requested_services": [],
        "session_status": {"flights": "pending", "lodging": "pending", "car": "pending", "trip_planning": "pending"},
    }
    r_b = _post("טסים לבארי שניים, ה-10 עד ה-15 באפריל.", [], state_fresh, member_b)
tu_b = r_b.get("trip_update") or {}
check("regression: a genuinely live, freshly-computed guided hint "
      "(accessibility, right after dates+travelers both resolved this "
      "same turn) is still produced normally - the fix only clears a "
      "STALE hint, never a live one",
      "התאמות נגישות" in str(tu_b.get("_guided_ask_hint") or ""))

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE email LIKE 'qa-dryrun2-%@example.com'")
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DRY-RUN-2 STALE-GUIDED-HINT TESTS PASSED")
