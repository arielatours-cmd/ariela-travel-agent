"""QA for the business owner's manual WhatsApp test (Croatia, trip 258,
16.10.2026, transcript in ceo/relay/2026-10-16-owner-whatsapp-croatia-
transcript.md) - the most severe of three bugs found, prioritized first by
Shlomo because it sends the real flight search to the wrong airports.

Live sequence: the route was approved with an open-jaw entry at Zagreb and
exit from Dubrovnik - correctly resolved by 16:10-16:11 (the flight summary
read "נחיתה זאגרב, המראה מ-DBV"). The customer then moved into the car
domain (vehicle type, pickup/return location). Right after confirming the
car's pickup/return airports, Ariella asked the gateway-narrowing question
again - "יש כמה שדות אפשריים ליעד הזה (ספליט או דוברובניק)..." - with
Zagreb missing entirely from the candidate list. The customer answered
"בשניהם" (both), and destination_airports/return_departure_airports ended
up wrong: the account page showed "דוברובניק • ספליט" and the real flight
search found nothing. A later explicit correction ("תתקני נחיתה בזאגרב,
המראה מדוברובניק") did not stick either.

Root cause: _resolve_destination_airports_from_route(state) re-runs on
EVERY turn, regardless of active_session. Its first block (an open-jaw
split derivation) correctly skips once return_departure_airports is
already set - but execution then fell through to the generic single-field
fallback a few lines below, which recomputes destination_airports from
the route's full list of overnight bases (e.g. Plitvice/Zadar/Trogir, or
any mix including the entry/exit cities) and overwrites the already-locked
single gateway with whatever that recomputation produces - silently
corrupting a decision that was supposed to be settled once. This also
explains why the LATER explicit correction didn't stick: the very same
unconditional re-derivation clobbered it again on a subsequent turn.

Fixed: once both destination_airports and return_departure_airports are
already present, the function returns immediately - an open-jaw gateway
decision, once both halves are resolved, is never revisited by this
deterministic safety net again (an explicit customer correction still
goes through the extractor, a separate path, untouched by this guard).

Run: python3 tools/qa_croatia_zagreb_gateway_survives_car_turn.py
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


def croatia_state(route_bases):
    return {
        "trip_type": "standard",
        "destination": {"places": ["קרואטיה"], "mode": "country", "status": "known"},
        "trip_planning": {
            "approved": True,
            "details": {"route": [{"day": i + 1, "base": b} for i, b in enumerate(route_bases)]},
        },
        "destination_airports": ["ZAG"],
        "return_departure_airports": ["DBV"],
    }


# --- 1. Exact live shape: route bases are the overnight stops only ---
state1 = croatia_state(["פלטביצה", "פלטביצה", "זדאר", "זדאר", "טרוגיר", "טרוגיר", "טרוגיר"])
result1 = chat._resolve_destination_airports_from_route(dict(state1))
check("overnight-only route bases: Zagreb gateway is NOT overwritten",
      result1.get("destination_airports") == ["ZAG"])
check("overnight-only route bases: Dubrovnik return gateway is NOT overwritten",
      result1.get("return_departure_airports") == ["DBV"])

# --- 2. Route bases also name the entry/exit cities explicitly (the shape
#        that reproduces the observed len>1 corruption most directly) ---
state2 = croatia_state(["זאגרב", "פלטביצה", "זדאר", "טרוגיר", "דוברובניק"])
result2 = chat._resolve_destination_airports_from_route(dict(state2))
check("entry/exit-named route bases: destination_airports stays a single gateway",
      result2.get("destination_airports") == ["ZAG"])
check("entry/exit-named route bases: return_departure_airports is untouched",
      result2.get("return_departure_airports") == ["DBV"])

# --- 3. Regression: the open-jaw split itself must still work on a FIRST
#        pass (return_departure_airports not yet set) ---
fresh_state = {
    "trip_type": "standard",
    "destination": {"places": ["קפריסין"], "mode": "country", "status": "known"},
    "trip_planning": {
        "approved": True,
        "details": {"route": [
            {"day": 1, "base": "פאפוס"}, {"day": 2, "base": "פאפוס"}, {"day": 3, "base": "לרנקה"},
        ]},
    },
}
fresh_result = chat._resolve_destination_airports_from_route(dict(fresh_state))
check("regression: a genuinely fresh open-jaw route still derives both gateways",
      bool(fresh_result.get("destination_airports")) and bool(fresh_result.get("return_departure_airports"))
      and fresh_result["destination_airports"] != fresh_result["return_departure_airports"])

# --- 4. Regression: single-base route (no open-jaw) still derives a gateway
#        normally when nothing is locked in yet ---
single_base_state = {
    "trip_type": "standard",
    "destination": {"places": ["יוון"], "mode": "country", "status": "known"},
    "trip_planning": {
        "approved": True,
        "details": {"route": [{"day": 1, "base": "אתונה"}, {"day": 2, "base": "אתונה"}]},
    },
}
single_result = chat._resolve_destination_airports_from_route(dict(single_base_state))
check("regression: a fresh single-base route still derives a gateway",
      bool(single_result.get("destination_airports")))

# --- 5. End-to-end: the same car-pickup-confirmation turn, through the
#        real chat-clean endpoint, with lodging already complete. This also
#        checks the business owner's second finding (bug 2: "תרצי שאמשיך
#        גם עם לינה?" reappearing even though lodging had already closed
#        at 16:13-16:14) - which this same fix turns out to resolve too,
#        since that symptom only happens once the bogus gateway-narrow
#        re-trigger (caused by the len(destination_airports)>1 corruption)
#        disrupts normal session progression. With destination_airports
#        correctly staying a single entry, no bogus re-trigger ever fires,
#        and lodging's session_status is never disturbed. ---
import database
database.init_db()
import app as app_module
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash
import sqlite3
from unittest.mock import patch

DB = database.DB_PATH
client = app_module.app.test_client()


def _fake_post_claude(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source in ("state_extractor", "classifier"):
        return "{}"
    return "תשובה לדוגמה."


def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA Croatia E2E", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


member_id = _make_member("qa-croatia-e2e@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id

E2E_STATE = {
    "trip_type": "standard",
    "destination": {"places": ["קרואטיה"], "mode": "country", "status": "known"},
    "destination_airports": ["ZAG"],
    "return_departure_airports": ["DBV"],
    "departure_airport": "TLV",
    "dates": {"departure": "2027-09-19", "return": "2027-09-30", "needs_confirmation": False},
    "travelers": {"adults": 2, "children": 2, "child_ages": [9, 11], "child_genders": ["male", "female"]},
    "budget_per_person": {"amount": 1000, "currency": "₪"},
    "flight": {"connection_preference": "direct", "baggage": ["carry_on_only"]},
    "trip_planning": {"approved": True, "details": {"route": [
        {"day": 1, "base": "זאגרב"}, {"day": 2, "base": "פלטביצה"}, {"day": 3, "base": "זדאר"},
        {"day": 4, "base": "טרוגיר"}, {"day": 5, "base": "דוברובניק"},
    ]}},
    "lodging": {"details": {"type": "דירה", "rooms": 2, "budget": 500, "locations": None}},
    "car": {"details": {"vehicle_type": "SUV", "transmission": "אוטומטי", "pickup": "זאגרב", "return": "דוברובניק"}},
    "requested_services": ["flights", "trip_planning", "lodging", "car"],
    "service_decisions": {
        "flights": {"wanted": True, "source": "x"}, "trip_planning": {"wanted": True, "source": "x"},
        "lodging": {"wanted": True, "source": "x"}, "car": {"wanted": True, "source": "x"},
    },
    "session_status": {"flights": "complete", "trip_planning": "complete", "lodging": "complete", "car": "active"},
    "active_session": "car",
}
E2E_HISTORY = [{"role": "assistant", "content": "תרצו לאסוף ולהחזיר בשדה (זאגרב לאיסוף, דוברובניק להחזרה), או שעדיף מיקום אחר?"}]

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r_e2e = client.post("/api/ariella/chat-clean", json={
        "message": "בשניהם", "history": E2E_HISTORY, "trip_state": dict(E2E_STATE),
    })
tu_e2e = (r_e2e.get_json() or {}).get("trip_update") or {}
check("e2e: destination_airports survives the car-domain turn intact",
      tu_e2e.get("destination_airports") == ["ZAG"])
check("e2e: return_departure_airports survives the car-domain turn intact",
      tu_e2e.get("return_departure_airports") == ["DBV"])
check("e2e (bug 2): lodging's session_status is never disturbed - stays complete",
      (tu_e2e.get("session_status") or {}).get("lodging") == "complete")
check("e2e (bug 2): car's session_status closes normally",
      (tu_e2e.get("session_status") or {}).get("car") == "complete")
check("e2e: with every domain genuinely complete, active_session clears for the final summary",
      tu_e2e.get("active_session") is None)

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL CROATIA-ZAGREB-GATEWAY-SURVIVES-CAR-TURN TESTS PASSED")
