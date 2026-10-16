"""QA for a non-blocking gap Shlomo flagged after PR #43 shipped (round 6,
2026-10-16): the open_places reopen-offer gate matches candidate vacations
by COUNTRY, not just city - so an active trip (e.g. Milan, with no
itinerary planned - only flights + lodging) could still get offered an
unrelated old vacation (Rome) just because both happen to be in Italy.

Root cause: _reopenable_trips's `message` parameter is overloaded across
its call sites - sometimes it's the customer's own free text (where "my
Italy vacation" legitimately has no city at all and country-level
matching is the right call), and sometimes (the open_places gate) it's
actually the CURRENT trip's own destination places, which are always
already specific - loosening to country level there is never justified,
since it's comparing the CURRENT destination against OTHER saved
vacations, not interpreting an ambiguous customer utterance.

Fixed by adding a `country_match` parameter (default True, preserving the
existing free-text call sites unchanged) and passing False from the
open_places gate specifically.

Note: Milan/Rome is used here rather than Sicily (Shlomo's own illustrative
example) because "סיציליה" is a region/island name, not itself a city or
country in the airport catalog that `_mentioned_places` draws from - it
is recognized as a destination only by the model's own extraction, never
by this deterministic matcher, so it can't exercise this code path at all
(mentioned ends up empty, which already short-circuits ALL filtering
regardless of country_match - a separate, pre-existing catalog-coverage
gap, not what this fix addresses). Milan and Rome are both real catalog
cities and exercise the actual country_match branch directly.

Run: python3 tools/qa_round6_reopen_gate_country_match.py
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
            ("QA Round6 Country Match", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def _make_reopenable_trip(member_id, name, destinations):
    answers = {
        "origin_airports": ["TLV"], "destinations": destinations,
        "departure_date": "2027-04-10", "return_date": "2027-04-17",
        "adults": 2,
    }
    with sqlite3.connect(DB) as conn:
        cur = conn.execute(
            "INSERT INTO trip_requests (member_id, request_name, travel_window, created_at, status, answers_json) VALUES(?,?,?,?,?,?)",
            (member_id, name, "10.4-17.4.2027", datetime.now(timezone.utc).isoformat(), "active", json.dumps(answers, ensure_ascii=False)),
        )
        return cur.lastrowid


member_id = _make_member("qa-round6-country-match@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id
_make_reopenable_trip(member_id, "רומא", "FCO")

# --- Unit-level check: _reopenable_trips itself ---
check("country_match=True (old default) still matches Rome for a Milan query (legacy behavior)",
      any(t["name"] == "רומא" for t in chat._reopenable_trips(member_id, "lodging", "מילאנו", limit=20, country_match=True)))
check("country_match=False excludes the unrelated same-country Rome vacation for a Milan query",
      not any(t["name"] == "רומא" for t in chat._reopenable_trips(member_id, "lodging", "מילאנו", limit=20, country_match=False)))

# --- End-to-end: the open_places gate (an ACTIVE lodging session on a
#     Milan trip, no itinerary) must not offer the unrelated Rome vacation
#     just because both are in Italy ---
milan_state = {
    "destination": {"places": ["מילאנו"], "mode": "specific", "status": "known"},
    "active_session": "lodging",
    "requested_services": ["flights", "lodging"],
    "session_status": {"flights": "complete", "lodging": "active", "car": "declined", "trip_planning": "declined"},
}
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r = client.post("/api/ariella/chat-clean", json={
        "message": "מלון 4 כוכבים בבקשה", "history": [], "trip_state": dict(milan_state),
    })
data = r.get_json()
check("a Milan lodging-detail answer does not get offered the unrelated Rome vacation via country",
      "לאיזו חופשה" not in str(data.get("reply") or "") and not (data.get("trip_update") or {}).get("reopen_trip_pending"))

# --- Regression guard: a genuinely matching SAME-CITY old vacation must
#     still be offered correctly ---
_make_reopenable_trip(member_id, "מילאנו", "MXP")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r2 = client.post("/api/ariella/chat-clean", json={
        "message": "מלון 4 כוכבים בבקשה", "history": [], "trip_state": dict(milan_state),
    })
data2 = r2.get_json()
check("a genuinely same-city old Milan vacation is still offered correctly",
      "לאיזו חופשה" in str(data2.get("reply") or "") or bool((data2.get("trip_update") or {}).get("reopen_trip_pending")))

# --- Regression guard: the free-text (trip_is_empty) call site must still
#     match via country when the customer's own words only name a country ---
empty_state = {}
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r3 = client.post("/api/ariella/chat-clean", json={
        "message": "אני רוצה לחזור לחופשה שלי באיטליה ולהוסיף לינה", "history": [], "trip_state": dict(empty_state),
    })
data3 = r3.get_json()
check("the free-text 'my Italy vacation' (trip_is_empty) case still matches via country as before",
      "לאיזו חופשה" in str(data3.get("reply") or "") or bool((data3.get("trip_update") or {}).get("reopen_trip_pending")))

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM trip_requests WHERE member_id=?", (member_id,))
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL ROUND6-REOPEN-GATE-COUNTRY-MATCH TESTS PASSED")
