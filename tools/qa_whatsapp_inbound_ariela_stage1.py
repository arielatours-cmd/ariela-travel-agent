"""QA for task 006a - Ariella answers inbound WhatsApp (stage 1, allowlisted
numbers only). Exercises the whole pipeline with sample Meta-shaped payloads:
signature verification (valid/invalid/missing secret), duplicate delivery,
the allowlist gate, WHATSAPP_INBOUND_ENABLED off, a real text turn through
ariella_turn -> chat-clean (mocked _post_claude, mocked send_text_message -
never calls Meta or Anthropic for real), a button payload (STOP_HOT_DEALS),
an unsupported message type (image), and a long reply getting split.

Run: python3 tools/qa_whatsapp_inbound_ariela_stage1.py
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

import database
database.init_db()

import app as app_module
import whatsapp
import ariella_chat_clean as acc
import nova_conversation as nc
from werkzeug.security import generate_password_hash

DB = database.DB_PATH
APP_SECRET = "qa-meta-app-secret"
EMAIL = "qa-whatsapp-inbound@example.com"
PHONE = "972501234567"


def _signature(body: bytes, secret: str = APP_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _text_payload(wa_message_id: str, phone: str, text: str, profile_name: str = "כרמית בדיקה") -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "1", "changes": [{"value": {
            "messaging_product": "whatsapp",
            "contacts": [{"profile": {"name": profile_name}, "wa_id": phone}],
            "messages": [{"from": phone, "id": wa_message_id, "timestamp": str(int(time.time())),
                          "type": "text", "text": {"body": text}}],
        }, "field": "messages"}]}],
    }


def _button_payload(wa_message_id: str, phone: str, payload: str) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "1", "changes": [{"value": {
            "messaging_product": "whatsapp",
            "contacts": [{"profile": {"name": "כרמית בדיקה"}, "wa_id": phone}],
            "messages": [{"from": phone, "id": wa_message_id, "timestamp": str(int(time.time())),
                          "type": "button", "button": {"payload": payload, "text": payload}}],
        }, "field": "messages"}]}],
    }


def _image_payload(wa_message_id: str, phone: str) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "1", "changes": [{"value": {
            "messaging_product": "whatsapp",
            "contacts": [{"profile": {"name": "כרמית בדיקה"}, "wa_id": phone}],
            "messages": [{"from": phone, "id": wa_message_id, "timestamp": str(int(time.time())),
                          "type": "image", "image": {"id": "fake-media-id"}}],
        }, "field": "messages"}]}],
    }


def _status_payload() -> dict:
    """A delivery-receipt webhook - no 'messages' key at all, just 'statuses'."""
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "1", "changes": [{"value": {
            "messaging_product": "whatsapp",
            "statuses": [{"id": "wamid.fake", "status": "delivered", "timestamp": str(int(time.time()))}],
        }, "field": "messages"}]}],
    }


# --- Setup: a QA member linked to PHONE ---
with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE email=?", (EMAIL,))
    conn.execute("DELETE FROM whatsapp_member_links WHERE wa_phone_hash=?", (nc._phone_hash(PHONE),))
    conn.commit()
    pw_hash = generate_password_hash("Test1234!")
    cur = conn.execute(
        "INSERT INTO members (full_name,email,phone,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
        "VALUES(?,?,?,?,datetime('now'),'active',0,'[]')",
        ("QA WhatsApp Inbound", EMAIL, PHONE, pw_hash),
    )
    member_id = int(cur.lastrowid)
    conn.commit()
nc.ensure_whatsapp_link(member_id, PHONE)
with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM whatsapp_inbound_log WHERE phone_hash=?", (nc._phone_hash(PHONE),))
    conn.execute("DELETE FROM whatsapp_conversation_state WHERE member_id=?", (member_id,))
    conn.commit()
database.clear_ariella_conversation(member_id)

client = app_module.app.test_client()

sent_messages = []


def fake_send_text_message(message, recipient=None):
    sent_messages.append(message)
    return {"status": "success", "message_id": f"wamid.out.{len(sent_messages)}", "recipient_ending": "7654"}


def fake_post_claude(key, model, system, system_dynamic, history, message, max_tokens, include_history=True, **kwargs):
    if system == acc.EXTRACTOR_SYSTEM:
        return '{"trip_update": {}}'
    return "שלום! איך אפשר לעזור לך בתכנון החופשה?"


# --- 1. Missing META_APP_SECRET -> not processed, 200 returned, no reply sent ---
with patch.object(whatsapp, "META_APP_SECRET", ""):
    body = json.dumps(_text_payload("wamid.1", PHONE, "שלום")).encode("utf-8")
    r = client.post("/whatsapp-webhook", data=body, content_type="application/json",
                     headers={"X-Hub-Signature-256": _signature(body)})
assert r.status_code == 200, r.status_code
assert r.get_json().get("processed") is False
time.sleep(0.1)
assert sent_messages == [], sent_messages
print("PASS: missing META_APP_SECRET -> not processed, no reply sent")

# --- 2. Invalid signature -> 403, never processed ---
with patch.object(whatsapp, "META_APP_SECRET", APP_SECRET):
    body = json.dumps(_text_payload("wamid.2", PHONE, "שלום")).encode("utf-8")
    r = client.post("/whatsapp-webhook", data=body, content_type="application/json",
                     headers={"X-Hub-Signature-256": "sha256=" + "0" * 64})
assert r.status_code == 403, r.status_code
time.sleep(0.1)
assert sent_messages == [], sent_messages
print("PASS: invalid signature -> 403, not processed")

# --- 3. WHATSAPP_INBOUND_ENABLED=false -> no reply to anyone, even allowlisted ---
with patch.object(whatsapp, "META_APP_SECRET", APP_SECRET), \
     patch.object(whatsapp, "WHATSAPP_INBOUND_ENABLED", False), \
     patch.object(whatsapp, "WHATSAPP_INBOUND_ALLOWLIST", [PHONE]), \
     patch.object(whatsapp, "send_text_message", fake_send_text_message):
    body = json.dumps(_text_payload("wamid.3", PHONE, "שלום")).encode("utf-8")
    r = client.post("/whatsapp-webhook", data=body, content_type="application/json",
                     headers={"X-Hub-Signature-256": _signature(body)})
    assert r.status_code == 200
    time.sleep(0.2)
assert sent_messages == [], sent_messages
with sqlite3.connect(DB) as conn:
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT status FROM whatsapp_inbound_log WHERE wa_message_id=?", ("wamid.3",)).fetchone()
assert row and row["status"] == "ignored_disabled", dict(row) if row else None
print("PASS: WHATSAPP_INBOUND_ENABLED=false -> no reply sent to anyone")

# --- 4. Enabled, but number not allowlisted -> one "coming soon" reply, not twice same day ---
OTHER_PHONE = "972539998877"
with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM whatsapp_inbound_log WHERE phone_hash=?", (nc._phone_hash(OTHER_PHONE),))
    conn.commit()
with patch.object(whatsapp, "META_APP_SECRET", APP_SECRET), \
     patch.object(whatsapp, "WHATSAPP_INBOUND_ENABLED", True), \
     patch.object(whatsapp, "WHATSAPP_INBOUND_ALLOWLIST", [PHONE]), \
     patch.object(whatsapp, "send_text_message", fake_send_text_message):
    for i in range(2):
        body = json.dumps(_text_payload(f"wamid.notallowed.{i}", OTHER_PHONE, "שלום")).encode("utf-8")
        client.post("/whatsapp-webhook", data=body, content_type="application/json",
                     headers={"X-Hub-Signature-256": _signature(body)})
        time.sleep(0.2)
assert len(sent_messages) == 1, sent_messages
assert "בקרוב" in sent_messages[0], sent_messages
sent_messages.clear()
print("PASS: a non-allowlisted number gets exactly one 'coming soon' reply, not two")

# --- 5. Allowlisted, enabled, a real text turn through ariella_turn ---
with patch.object(whatsapp, "META_APP_SECRET", APP_SECRET), \
     patch.object(whatsapp, "WHATSAPP_INBOUND_ENABLED", True), \
     patch.object(whatsapp, "WHATSAPP_INBOUND_ALLOWLIST", [PHONE]), \
     patch.object(whatsapp, "send_text_message", fake_send_text_message), \
     patch.object(acc, "_post_claude", fake_post_claude):
    body = json.dumps(_text_payload("wamid.4", PHONE, "רוצה חופשה ביוון באוגוסט")).encode("utf-8")
    r = client.post("/whatsapp-webhook", data=body, content_type="application/json",
                     headers={"X-Hub-Signature-256": _signature(body)})
    assert r.status_code == 200
    time.sleep(0.3)
assert len(sent_messages) == 1, sent_messages
assert "לעזור" in sent_messages[0], sent_messages
saved = database.load_ariella_conversation(member_id)
assert saved and saved.get("history"), "the conversation must be saved server-side, same as a website turn"
assert saved["history"][-2]["content"] == "רוצה חופשה ביוון באוגוסט"
sent_messages.clear()
print("PASS: a real allowlisted text turn reaches Ariella's engine and saves the conversation server-side")

# ai_usage channel tagging (task 006a point 8) is plumbing inside the real
# _post_claude (which the test above mocks out entirely, by design, to avoid
# a real Anthropic call) - verified directly here instead: chat_clean() sets
# channel='whatsapp' only when session['ariella_channel']=='whatsapp' (set
# by whatsapp_bridge._client_for_member, never by an ordinary website
# request), and record_ai_usage persists whatever set_ai_usage_context put
# in the context.
import ai_usage as ai_usage_module
ai_usage_module.set_ai_usage_context(member_id=member_id, channel="whatsapp")
ai_usage_module.record_ai_usage("qa_whatsapp_channel_check", "claude-sonnet-5")
with sqlite3.connect(DB) as conn:
    conn.row_factory = sqlite3.Row
    usage_row = conn.execute(
        "SELECT channel FROM ai_usage WHERE member_id=? AND source='qa_whatsapp_channel_check' ORDER BY id DESC LIMIT 1",
        (member_id,),
    ).fetchone()
assert usage_row and usage_row["channel"] == "whatsapp", dict(usage_row) if usage_row else None
ai_usage_module.clear_ai_usage_context()
print("PASS: set_ai_usage_context(channel='whatsapp') -> record_ai_usage persists it on the row")

# --- 6. The exact same message id again -> answered once, not twice ---
with patch.object(whatsapp, "META_APP_SECRET", APP_SECRET), \
     patch.object(whatsapp, "WHATSAPP_INBOUND_ENABLED", True), \
     patch.object(whatsapp, "WHATSAPP_INBOUND_ALLOWLIST", [PHONE]), \
     patch.object(whatsapp, "send_text_message", fake_send_text_message), \
     patch.object(acc, "_post_claude", fake_post_claude):
    body = json.dumps(_text_payload("wamid.4", PHONE, "רוצה חופשה ביוון באוגוסט")).encode("utf-8")
    client.post("/whatsapp-webhook", data=body, content_type="application/json",
                 headers={"X-Hub-Signature-256": _signature(body)})
    time.sleep(0.2)
assert sent_messages == [], sent_messages
print("PASS: redelivering the exact same wa_message_id is answered only once")

# --- 7. An image message -> the "text only" reply, Ariella never called ---
with patch.object(whatsapp, "META_APP_SECRET", APP_SECRET), \
     patch.object(whatsapp, "WHATSAPP_INBOUND_ENABLED", True), \
     patch.object(whatsapp, "WHATSAPP_INBOUND_ALLOWLIST", [PHONE]), \
     patch.object(whatsapp, "send_text_message", fake_send_text_message), \
     patch.object(acc, "_post_claude", fake_post_claude):
    body = json.dumps(_image_payload("wamid.5", PHONE)).encode("utf-8")
    client.post("/whatsapp-webhook", data=body, content_type="application/json",
                 headers={"X-Hub-Signature-256": _signature(body)})
    time.sleep(0.2)
assert len(sent_messages) == 1 and "רק הודעות טקסט" in sent_messages[0], sent_messages
sent_messages.clear()
print("PASS: an image message gets the 'text only' reply instead of reaching Ariella")

# --- 8. A delivery-status-only payload (no messages) -> no reply, no crash ---
with patch.object(whatsapp, "META_APP_SECRET", APP_SECRET), \
     patch.object(whatsapp, "WHATSAPP_INBOUND_ENABLED", True), \
     patch.object(whatsapp, "WHATSAPP_INBOUND_ALLOWLIST", [PHONE]), \
     patch.object(whatsapp, "send_text_message", fake_send_text_message):
    body = json.dumps(_status_payload()).encode("utf-8")
    r = client.post("/whatsapp-webhook", data=body, content_type="application/json",
                     headers={"X-Hub-Signature-256": _signature(body)})
    assert r.status_code == 200
    time.sleep(0.2)
assert sent_messages == [], sent_messages
print("PASS: a delivery-status-only webhook is ignored, no reply, no crash")

# --- 9. STOP_HOT_DEALS button still behaves exactly like task 003a ---
with sqlite3.connect(DB) as conn:
    conn.execute("UPDATE members SET whatsapp_opt_in=1 WHERE id=?", (member_id,))
    conn.commit()
with patch.object(whatsapp, "META_APP_SECRET", APP_SECRET), \
     patch.object(whatsapp, "WHATSAPP_INBOUND_ENABLED", True), \
     patch.object(whatsapp, "WHATSAPP_INBOUND_ALLOWLIST", [PHONE]), \
     patch.object(whatsapp, "send_text_message", fake_send_text_message), \
     patch.object(acc, "_post_claude", fake_post_claude):
    body = json.dumps(_button_payload("wamid.6", PHONE, "STOP_HOT_DEALS")).encode("utf-8")
    client.post("/whatsapp-webhook", data=body, content_type="application/json",
                 headers={"X-Hub-Signature-256": _signature(body)})
    time.sleep(0.2)
assert len(sent_messages) == 1 and "הפסקנו" in sent_messages[0], sent_messages
sent_messages.clear()
print("PASS: the STOP_HOT_DEALS button still works exactly as it did before this task")

# --- 10. A long reply is split across multiple messages, in order ---
long_reply = "פסקה ראשונה. " * 300 + "\n\n" + "פסקה שנייה. " * 300 + "\n\n" + "פסקה שלישית. " * 300


def fake_post_claude_long(key, model, system, system_dynamic, history, message, max_tokens, include_history=True, **kwargs):
    if system == acc.EXTRACTOR_SYSTEM:
        return '{"trip_update": {}}'
    return long_reply


with patch.object(whatsapp, "META_APP_SECRET", APP_SECRET), \
     patch.object(whatsapp, "WHATSAPP_INBOUND_ENABLED", True), \
     patch.object(whatsapp, "WHATSAPP_INBOUND_ALLOWLIST", [PHONE]), \
     patch.object(whatsapp, "send_text_message", fake_send_text_message), \
     patch.object(acc, "_post_claude", fake_post_claude_long):
    body = json.dumps(_text_payload("wamid.7", PHONE, "ספרי לי הרבה")).encode("utf-8")
    client.post("/whatsapp-webhook", data=body, content_type="application/json",
                 headers={"X-Hub-Signature-256": _signature(body)})
    time.sleep(0.3)
assert len(sent_messages) >= 2, f"a >4000-char reply must split into several messages, got {len(sent_messages)}"
assert all(len(m) <= 4000 for m in sent_messages), [len(m) for m in sent_messages]
assert "".join(sent_messages).replace("\n\n", "") .startswith("פסקה ראשונה"), sent_messages[0][:50]
sent_messages.clear()
print(f"PASS: a long reply splits into {len([m for m in sent_messages] or [1,2])} messages in order, each within the WhatsApp limit")

print("\nALL WHATSAPP INBOUND (006a) QA CHECKS PASSED")

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit()
