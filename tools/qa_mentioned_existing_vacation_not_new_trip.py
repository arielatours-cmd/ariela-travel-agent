"""QA for A7 item 1 (Shaked, qa-s91, round 2, 2026-10-15, trip 222): while
mid-conversation about one vacation (Paris), "אני רוצה לחזור לחופשה שלי
לאיטליה באפריל ולהוסיף לה לינה ורכב" (I want to return to my Italy vacation
and add lodging and a car to it) named a destination that is itself one of
the customer's own saved upcoming vacations, in the same breath as asking
to add specific services - but Ariella answered "חופשה חדשה או שינוי יעד
לפריז?" (new vacation, or change the destination of the Paris trip?),
because the known-destination-mention loop that decides "possible new
trip" vs "destination change" never checked whether the mentioned place
was itself one of the customer's own saved vacations before reaching for
those two options. Neither option means "the existing one I already have".

Fixed by checking, right where "possible new trip" is about to be set, for
a reopenable vacation matching the mentioned destination when the message
also names a service to add - if found, the reopen_trip_pending mechanism
(with keep_state so declining it resumes the CURRENT trip unaffected, same
as the open-conversation reopen offer) takes over before ever reaching
"new vacation or change destination".

Run: python3 tools/qa_mentioned_existing_vacation_not_new_trip.py
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
from datetime import datetime, timezone, timedelta
from werkzeug.security import generate_password_hash
import sqlite3
import json

DB = database.DB_PATH
client = app_module.app.test_client()

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


def _fake_post_claude(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return "{}"
    return "תשובה לדוגמה."


def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA Existing Vacation Mention", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def _make_trip(member_id, name, destinations, dep, ret):
    answers = {
        "origin_airports": ["TLV"], "destinations": destinations,
        "departure_date": dep, "return_date": ret, "adults": 2,
    }
    with sqlite3.connect(DB) as conn:
        cur = conn.execute(
            "INSERT INTO trip_requests (member_id, request_name, travel_window, created_at, status, answers_json) VALUES(?,?,?,?,?,?)",
            (member_id, name, f"{dep} - {ret}", datetime.now(timezone.utc).isoformat(), "active", json.dumps(answers, ensure_ascii=False)),
        )
        return cur.lastrowid


member_id = _make_member("qa-existing-mention@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id

future_dep = (datetime.now(timezone.utc) + timedelta(days=180)).date().isoformat()
future_ret = (datetime.now(timezone.utc) + timedelta(days=187)).date().isoformat()
_make_trip(member_id, "איטליה", "FCO", future_dep, future_ret)

paris_state = {
    "destination": {"places": ["פריז"], "mode": "specific", "status": "known"},
    "active_session": None,
    "requested_services": ["flights"],
    "session_status": {"flights": "complete", "lodging": "pending", "car": "pending", "trip_planning": "pending"},
}

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r = client.post("/api/ariella/chat-clean", json={
        "message": "אני רוצה לחזור לחופשה שלי לאיטליה באפריל ולהוסיף לה לינה ורכב",
        "history": [{"role": "assistant", "content": "בשמחה, ממשיכים עם החופשה לפריז."}],
        "trip_state": dict(paris_state),
    })
data = r.get_json()
reply = str(data.get("reply") or "")
trip_update = data.get("trip_update") or {}
check("mentioning an existing saved vacation is never offered as 'new vacation or change destination'",
      "חופשה חדשה או שינוי יעד" not in reply)
check("the reopen mechanism is used instead (either the reopen question or reopen_trip_pending set)",
      bool(trip_update.get("reopen_trip_pending")))
pending = trip_update.get("reopen_trip_pending") or {}
check("both explicitly requested services are carried into the reopen offer",
      set(pending.get("services") or []) == {"lodging", "car"})
check("declining the reopen offer must resume the CURRENT trip (Paris), not discard it (keep_state)",
      bool(pending.get("keep_state")))

# --- Declining it resumes the Paris trip untouched ---
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r2 = client.post("/api/ariella/chat-clean", json={
        "message": "לא, זו חופשה חדשה ונפרדת", "history": [], "trip_state": trip_update,
    })
data2 = r2.get_json()
trip_update2 = data2.get("trip_update") or {}
check("declining the reopen offer keeps the Paris destination intact (never discarded)",
      "פריז" in ((trip_update2.get("destination") or {}).get("places") or []))

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM trip_requests WHERE member_id=?", (member_id,))
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL MENTIONED-EXISTING-VACATION-NOT-NEW-TRIP TESTS PASSED")
