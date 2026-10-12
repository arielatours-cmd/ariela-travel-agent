"""QA for task 006c - three admin GET routes that register
WHATSAPP_PHONE_NUMBER_ID directly on the Cloud API (request-code,
verify-code, register), replacing Coexistence which kept getting stuck.
All Meta Graph API calls are mocked - no real network call is ever made.

Run: python3 tools/qa_whatsapp_register_number.py
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

import app as app_module
import whatsapp

client = app_module.app.test_client()


def _ok(payload, status=200):
    resp = MagicMock()
    resp.ok = True
    resp.status_code = status
    resp.json.return_value = payload
    return resp


def _err(payload, status=400):
    resp = MagicMock()
    resp.ok = False
    resp.status_code = status
    resp.json.return_value = payload
    return resp


# --- 1. No admin token -> 401 on all three routes ---
with patch.object(app_module, "ADMIN_TOKEN", "real-admin-secret"):
    for path in ("/admin/whatsapp-number/request-code", "/admin/whatsapp-number/verify-code",
                 "/admin/whatsapp-number/register"):
        r = client.get(path)
        assert r.status_code == 401, (path, r.status_code)
print("PASS: no admin token -> 401 on all three routes")

# --- 2. Without confirm=1, no Meta call is ever made ---
with patch.object(whatsapp, "WHATSAPP_ACCESS_TOKEN", "fake-token"), \
     patch.object(whatsapp, "WHATSAPP_PHONE_NUMBER_ID", "551450234708715"), \
     patch.object(whatsapp, "WHATSAPP_REGISTRATION_PIN", "123456"), \
     patch("requests.post") as mock_post:
    r1 = whatsapp.whatsapp_request_code(method="SMS", confirm=False)
    r2 = whatsapp.whatsapp_verify_code("123456", confirm=False)
    r3 = whatsapp.whatsapp_register_number(confirm=False)
    assert mock_post.call_count == 0, mock_post.call_count
    assert r1["ok"] and r2["ok"] and r3["ok"]
print("PASS: without confirm=1, no Meta call is ever made (all three steps)")

# --- 3. request-code -> POST with code_method; verify-code -> POST with code; register -> POST with pin ---
with patch.object(whatsapp, "WHATSAPP_ACCESS_TOKEN", "fake-token"), \
     patch.object(whatsapp, "WHATSAPP_PHONE_NUMBER_ID", "551450234708715"), \
     patch.object(whatsapp, "WHATSAPP_REGISTRATION_PIN", "123456"), \
     patch("requests.post", return_value=_ok({"success": True})) as mock_post:
    r = whatsapp.whatsapp_request_code(method="VOICE", confirm=True)
    assert r["ok"] is True and r["sent"] is True, r
    assert mock_post.call_args.kwargs["data"] == {"code_method": "VOICE", "language": "he"}
    assert mock_post.call_args.args[0].endswith("/request_code")
print("PASS: request-code (confirm=1) -> POST with code_method=VOICE, language=he")

with patch.object(whatsapp, "WHATSAPP_ACCESS_TOKEN", "fake-token"), \
     patch.object(whatsapp, "WHATSAPP_PHONE_NUMBER_ID", "551450234708715"), \
     patch("requests.post", return_value=_ok({"success": True})) as mock_post:
    r = whatsapp.whatsapp_verify_code("12 34-56", confirm=True)
    assert r["ok"] is True and r["verified"] is True, r
    assert mock_post.call_args.kwargs["data"] == {"code": "123456"}, mock_post.call_args.kwargs
    assert mock_post.call_args.args[0].endswith("/verify_code")
print("PASS: verify-code (confirm=1) -> POST with digits-only code, non-digit chars stripped")

with patch.object(whatsapp, "WHATSAPP_ACCESS_TOKEN", "fake-token"), \
     patch.object(whatsapp, "WHATSAPP_PHONE_NUMBER_ID", "551450234708715"), \
     patch.object(whatsapp, "WHATSAPP_REGISTRATION_PIN", "654321"), \
     patch("requests.post", return_value=_ok({"success": True})) as mock_post, \
     patch("requests.get", return_value=_ok({"status": "CONNECTED", "platform_type": "CLOUD_API", "code_verification_status": "VERIFIED"})):
    r = whatsapp.whatsapp_register_number(confirm=True)
    assert r["ok"] is True and r["registered"] is True, r
    assert mock_post.call_args.kwargs["json"] == {"messaging_product": "whatsapp", "pin": "654321"}
    assert r["status"] == "CONNECTED" and r["platform_type"] == "CLOUD_API"
print("PASS: register (confirm=1) -> POST with messaging_product+pin, then re-checks status -> CONNECTED")

# --- 3b. A generic Meta error message (e.g. request_code's bare "Request code error")
# gets type/code/subcode/fbtrace_id appended so it's actually diagnosable ---
with patch.object(whatsapp, "WHATSAPP_ACCESS_TOKEN", "fake-token"), \
     patch.object(whatsapp, "WHATSAPP_PHONE_NUMBER_ID", "551450234708715"), \
     patch("requests.post", return_value=_err({"error": {
         "message": "Request code error", "type": "OAuthException", "code": 133010,
         "error_subcode": 2593006, "fbtrace_id": "AbCdEfGhIjK",
     }})):
    r = whatsapp.whatsapp_request_code(method="SMS", confirm=True)
    assert r["ok"] is False
    joined = " ".join(r["errors"])
    assert "Request code error" in joined and "code=133010" in joined and "subcode=2593006" in joined and "fbtrace_id=AbCdEfGhIjK" in joined, r["errors"]
print("PASS: a generic Meta error gets type/code/subcode/fbtrace_id appended for real diagnosis")

# --- 4. Meta errors are returned as-is (no secrets); "still linked to app" gets a clear Hebrew hint ---
with patch.object(whatsapp, "WHATSAPP_ACCESS_TOKEN", "fake-token"), \
     patch.object(whatsapp, "WHATSAPP_PHONE_NUMBER_ID", "551450234708715"), \
     patch.object(whatsapp, "WHATSAPP_REGISTRATION_PIN", "654321"), \
     patch("requests.post", return_value=_err({"error": {"message": "Phone number is still linked to an app (Coexistence)."}})):
    r = whatsapp.whatsapp_register_number(confirm=True)
    assert r["ok"] is False
    assert any("Phone number is still linked" in e for e in r["errors"]), r["errors"]
    assert any("עדיין מקושר" in e for e in r["errors"]), r["errors"]
print("PASS: Meta's 'still linked to app' error gets a clear Hebrew hint appended, original message preserved")

# --- 5. register without WHATSAPP_REGISTRATION_PIN configured -> clear message, no Meta call ---
with patch.object(whatsapp, "WHATSAPP_ACCESS_TOKEN", "fake-token"), \
     patch.object(whatsapp, "WHATSAPP_PHONE_NUMBER_ID", "551450234708715"), \
     patch.object(whatsapp, "WHATSAPP_REGISTRATION_PIN", ""), \
     patch("requests.post") as mock_post:
    r = whatsapp.whatsapp_register_number(confirm=True)
    assert r["ok"] is False and mock_post.call_count == 0, (r, mock_post.call_count)
    assert any("PIN" in e for e in r["errors"]), r["errors"]
print("PASS: register without WHATSAPP_REGISTRATION_PIN -> clear message, no Meta call at all")

# --- 6. The PIN and the access token never appear anywhere in any returned result ---
import json as _json
dump = _json.dumps(r1) + _json.dumps(r2) + _json.dumps(r3)
assert "fake-token" not in dump and "654321" not in dump and "123456" not in dump
print("PASS: neither the access token nor the PIN ever appears in a returned result")

print("\nALL WHATSAPP REGISTER NUMBER (006c) TESTS PASSED")
