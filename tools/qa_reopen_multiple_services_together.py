"""QA for a live bug Shaked found mid-round-2 (qa-s91, 2026-10-15, trip 222,
Italy vacation): "אני רוצה לחזור לחופשה שלי לאיטליה באפריל ולהוסיף לה לינה
ורכב" (I want to return to my Italy vacation and add BOTH lodging AND a car
to it) asked for two services in the same sentence. The reopen flow only
ever captured ONE service (whichever _explicit_service_request/
_classify_service_request happened to match first), so the other one was
recorded by _state_from_trip as reopened_trip_not_requested - never asked,
never wanted - even though the same message explicitly asked for it. Once
the customer later asked for the dropped service separately, completing it
in turn silently wiped out the FIRST service's just-settled decision too
(lodging.wanted=false, source=explicit_only_flights), because each reopen
rebuilt the whole service_decisions map from the DB's last-saved answers
with no memory of what this conversation had just settled.

Fixed via _all_requested_services (collects every service keyword in the
message, not just the first) and _state_from_trip now taking the full list:
the one chosen for the question this turn gets `active`, every other
co-requested one gets `wanted:true` + `pending` (never `declined`/
`reopened_trip_not_requested`) so the existing sessionizer
(_sessionize_state, run every later turn via _advance_sessions) naturally
activates it next once the first closes - the same mechanism already used
for any other multi-service request.

Run: python3 tools/qa_reopen_multiple_services_together.py
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
            ("QA Reopen Multi", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
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


member_id = _make_member("qa-reopen-multi@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id

future_dep = (datetime.now(timezone.utc) + timedelta(days=180)).date().isoformat()
future_ret = (datetime.now(timezone.utc) + timedelta(days=187)).date().isoformat()
trip_id = _make_trip(member_id, "איטליה", "FCO", future_dep, future_ret)

# --- 1. _all_requested_services collects BOTH services from one sentence ---
check("_all_requested_services finds both lodging and car in one sentence",
      set(chat._all_requested_services("אני רוצה לחזור לחופשה שלי לאיטליה ולהוסיף לה לינה ורכב", {})) == {"lodging", "car"})

# --- 2. _state_from_trip(trip, ["lodging","car"]): the primary is active,
#        the co-requested one is wanted:true + pending - never declined ---
trip_row = {"id": trip_id, "name": "איטליה", "window": "x", "answers": {
    "origin_airports": ["TLV"], "destinations": "FCO", "departure_date": future_dep, "return_date": future_ret, "adults": 2,
}}
state = chat._state_from_trip(trip_row, ["lodging", "car"])
check("the primary service (lodging) is active",
      state["session_status"]["lodging"] == "active")
check("the co-requested service (car) is wanted:true, never declined",
      state["service_decisions"]["car"].get("wanted") is True and state["session_status"]["car"] != "declined")
check("car's source is reopened_trip, not reopened_trip_not_requested",
      state["service_decisions"]["car"].get("source") == "reopened_trip")
check("car is queued (pending), not forced active alongside lodging",
      state["session_status"]["car"] == "pending")
check("trip_planning (never mentioned) is correctly declined as not requested",
      state["service_decisions"]["trip_planning"].get("source") == "reopened_trip_not_requested")
check("requested_services carries both lodging and car",
      {"lodging", "car"} <= set(state["requested_services"]))

# --- 3. End to end: asking to reopen a vacation for two services keeps both ---
with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM trip_requests WHERE id=?", (trip_id,))
    conn.commit()
trip_id2 = _make_trip(member_id, "איטליה", "FCO", future_dep, future_ret)

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r1 = client.post("/api/ariella/chat-clean", json={
        "message": "אני רוצה לחזור לחופשה שלי לאיטליה ולהוסיף לה לינה ורכב", "history": [], "trip_state": {},
    })
data1 = r1.get_json()
trip_update1 = data1.get("trip_update") or {}
pending1 = trip_update1.get("reopen_trip_pending") or {}
check("the reopen offer records both services, not just one",
      set(pending1.get("services") or []) == {"lodging", "car"})

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r2 = client.post("/api/ariella/chat-clean", json={
        "message": "כן", "history": [{"role": "assistant", "content": data1.get("reply") or ""}], "trip_state": trip_update1,
    })
data2 = r2.get_json()
trip_update2 = data2.get("trip_update") or {}
check("after choosing the vacation, car is still wanted (not dropped)",
      bool((trip_update2.get("service_decisions") or {}).get("car", {}).get("wanted")))
check("car's source after reopening is reopened_trip, not reopened_trip_not_requested",
      (trip_update2.get("service_decisions") or {}).get("car", {}).get("source") == "reopened_trip")
check("lodging is the active session (the one asked about this turn)",
      trip_update2.get("active_session") == "lodging")

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM trip_requests WHERE member_id=?", (member_id,))
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL REOPEN-MULTIPLE-SERVICES-TOGETHER TESTS PASSED")
