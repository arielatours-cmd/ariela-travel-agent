"""QA for task 016a Stage 4: WhatsApp wiring for a background route build.

Per Ofek's spec section 4: the WhatsApp inbound webhook is already fully
async (whatsapp.py answers Meta immediately and does all real work,
ariella_turn included, in a background thread - see that module's own
docstring), so there is no 502/edge-timeout risk there like the website
has. The customer still deserves the same quick "I'm building your route"
message instead of silence for up to 150s, and the real route once ready,
as TWO separate free-form WhatsApp messages (ariella_turn/
_poll_and_send_route_build in whatsapp_bridge.py).

Drives the real /whatsapp-webhook endpoint end to end (not unit-level
calls), with send_text_message and _post_claude both mocked - never calls
Meta or Anthropic for real.

Run: python3 tools/qa_016a_whatsapp_route_build.py
"""
import hashlib
import hmac
import json
import os
import sqlite3
import sys
import time
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ["ROUTE_BUILD_ASYNC"] = "1"

import database
database.init_db()

import app as app_module
import whatsapp
import ariella_chat_clean as acc
import nova_conversation as nc
import whatsapp_bridge
from werkzeug.security import generate_password_hash

DB = database.DB_PATH
APP_SECRET = "qa-016a-meta-app-secret"
EMAIL = "qa-016a-whatsapp-route@example.com"
PHONE = "972501234999"

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


def _signature(body: bytes, secret: str = APP_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _text_payload(wa_message_id: str, phone: str, text: str) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "1", "changes": [{"value": {
            "messaging_product": "whatsapp",
            "contacts": [{"profile": {"name": "QA 016a"}, "wa_id": phone}],
            "messages": [{"from": phone, "id": wa_message_id, "timestamp": str(int(time.time())),
                          "type": "text", "text": {"body": text}}],
        }, "field": "messages"}]}],
    }


# --- Setup: a QA member linked to PHONE, with trip_state already one step from a route ---
with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE email=?", (EMAIL,))
    conn.execute("DELETE FROM whatsapp_member_links WHERE wa_phone_hash=?", (nc._phone_hash(PHONE),))
    conn.commit()
    pw_hash = generate_password_hash("Test1234!")
    cur = conn.execute(
        "INSERT INTO members (full_name,email,phone,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
        "VALUES(?,?,?,?,datetime('now'),'active',0,'[]')",
        ("QA 016a WhatsApp Route", EMAIL, PHONE, pw_hash),
    )
    member_id = int(cur.lastrowid)
    conn.commit()
nc.ensure_whatsapp_link(member_id, PHONE)
with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM whatsapp_inbound_log WHERE phone_hash=?", (nc._phone_hash(PHONE),))
    conn.execute("DELETE FROM whatsapp_conversation_state WHERE member_id=?", (member_id,))
    conn.commit()

ROUTE_READY_TRIP_STATE = {
    "destination": {"places": ["רומא"], "mode": "specific", "status": "known"},
    "dates": {"departure": "2027-06-01", "return": "2027-06-08"},
    "travelers": {"adults": 2, "children": 0},
    "requested_services": ["flights", "trip_planning"],
    "service_decisions": {"flights": {"wanted": True}, "trip_planning": {"wanted": True}},
    "session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "active"},
    "active_session": "trip_planning",
    "trip_planning": {"interested": True, "details": {"style": "תרבות", "pace": "relaxed"}},
}
database.save_ariella_conversation(member_id, [], ROUTE_READY_TRIP_STATE)

client = app_module.app.test_client()
sent_messages = []


def fake_send_text_message(message, recipient=None):
    sent_messages.append(message)
    return {"status": "success", "message_id": f"wamid.out.{len(sent_messages)}", "recipient_ending": "4999"}


def fake_post_claude_route(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other", **kwargs):
    if source == "route_ack":
        return "אני בונה לכם את המסלול עכשיו, רגע קטן!"
    if source == "state_extractor":
        return json.dumps({"trip_update": {}})
    return "יום 1: נחיתה ברומא. יום 2: סיור בעיר העתיקה."


with patch.object(whatsapp, "META_APP_SECRET", APP_SECRET), \
     patch.object(whatsapp, "WHATSAPP_INBOUND_ENABLED", True), \
     patch.object(whatsapp, "WHATSAPP_INBOUND_ALLOWLIST", [PHONE]), \
     patch.object(whatsapp, "send_text_message", fake_send_text_message), \
     patch.object(acc, "_post_claude", fake_post_claude_route):
    body = json.dumps(_text_payload("wamid.016a.1", PHONE, "תציעי מסלול בבקשה")).encode("utf-8")
    resp = client.post("/whatsapp-webhook", data=body, content_type="application/json",
                        headers={"X-Hub-Signature-256": _signature(body)})
    check("webhook itself returns fast (200 immediately, real work is backgrounded)", resp.status_code == 200)

    # The webhook's own background thread dispatches a route-build job, sends
    # the ack, then blocks polling (real 2s sleeps) until it's ready - give it
    # real wall-clock time rather than a fixed short sleep.
    deadline = time.time() + 15
    while time.time() < deadline and len(sent_messages) < 2:
        time.sleep(0.5)

check("exactly two messages were sent (ack, then the real route)", len(sent_messages) == 2)
if len(sent_messages) >= 1:
    check("the first message is the quick ack, not the real route", sent_messages[0] == "אני בונה לכם את המסלול עכשיו, רגע קטן!")
if len(sent_messages) >= 2:
    check("the second message is the real, fully-processed route", "יום 1" in sent_messages[1] and "יום 2" in sent_messages[1])

# --- The real route was also persisted server-side via the normal engine path ---
saved = database.load_ariella_conversation(member_id) or {}
saved_history = saved.get("history") or []
check("the real route reply made it into the persisted conversation history too",
      any("יום 1" in str(m.get("content") or "") for m in saved_history))

print()
if FAILED:
    print(f"FAILED ({len(FAILED)}): {FAILED}")
    sys.exit(1)
print("ALL 016A-WHATSAPP-ROUTE-BUILD TESTS PASSED")
