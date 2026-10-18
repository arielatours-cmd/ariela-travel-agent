"""QA for task 006b - GET /admin/whatsapp-subscription, which checks (and,
with ?apply=1, fixes) whether this app is subscribed to the configured WABA's
messages webhook. All Meta Graph API calls are mocked - no real network call
is ever made by this script.

Run: python3 tools/qa_whatsapp_subscription_check.py
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
from whatsapp_coexistence import META_APP_ID

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


PHONE_JSON = {
    "id": "551450234708715", "display_phone_number": "+972501234567",
    "verified_name": "Ariela Tours", "quality_rating": "GREEN",
    "platform_type": "CLOUD_API", "code_verification_status": "VERIFIED",
    "status": "CONNECTED",
}
NOT_SUBSCRIBED = {"data": [{"whatsapp_business_api_data": {"id": "999999999999999", "name": "Some Other App"}}]}
SUBSCRIBED = {"data": [{"whatsapp_business_api_data": {"id": META_APP_ID, "name": "ARIELA TOURS"}}]}

# --- 1. No admin token -> 401 ---
with patch.object(app_module, "ADMIN_TOKEN", "real-admin-secret"):
    r = client.get("/admin/whatsapp-subscription")
assert r.status_code == 401, r.status_code
print("PASS: no admin token -> 401")

# --- 2. No WHATSAPP_ACCESS_TOKEN -> token_ok:false with a clear message ---
with patch.object(whatsapp, "WHATSAPP_ACCESS_TOKEN", ""), \
     patch.object(whatsapp, "WHATSAPP_PHONE_NUMBER_ID", "551450234708715"):
    result = whatsapp.whatsapp_subscription_check(apply=False)
assert result["token_ok"] is False and result["errors"], result
print("PASS: missing WHATSAPP_ACCESS_TOKEN -> token_ok:false with a message")

# --- 3. WABA not subscribed -> subscribed:false (read-only, no POST); apply=1 -> POST sent, subscribed:true ---
posts = []

def fake_get(url, headers=None, params=None, timeout=None):
    if url.endswith("/551450234708715"):
        return _ok(PHONE_JSON)
    if url.endswith("/subscribed_apps"):
        return _ok(SUBSCRIBED if posts else NOT_SUBSCRIBED)
    raise AssertionError(f"unexpected GET {url}")

def fake_post(url, headers=None, timeout=None):
    posts.append(url)
    return _ok({"success": True})

with patch.object(whatsapp, "WHATSAPP_ACCESS_TOKEN", "fake-token"), \
     patch.object(whatsapp, "WHATSAPP_PHONE_NUMBER_ID", "551450234708715"), \
     patch.object(whatsapp, "WHATSAPP_WABA_ID", "453734811161130"), \
     patch("requests.get", side_effect=fake_get), \
     patch("requests.post", side_effect=fake_post):
    before = whatsapp.whatsapp_subscription_check(apply=False)
    assert before["subscribed"] is False and not posts, before
    assert before["phone"]["display_phone_number_ending"] == "4567"
    assert "display_phone_number" not in before["phone"], "full phone number must never be exposed"
    print("PASS: not subscribed, no POST without apply=1, phone masked to last 4 digits")

    after = whatsapp.whatsapp_subscription_check(apply=True)
    assert after["applied"] is True and len(posts) == 1 and after["subscribed"] is True, after
    print("PASS: apply=1 -> POST subscribed_apps sent once, re-checked, subscribed becomes true")

# --- 4. Token scoped to a different WABA (Meta permission error) -> token_ok:false, error shown ---
def fake_get_perm_error(url, headers=None, params=None, timeout=None):
    if url.endswith("/551450234708715"):
        return _ok(PHONE_JSON)
    if url.endswith("/subscribed_apps"):
        return _err({"error": {"message": "(#200) Permission denied for this WABA", "type": "OAuthException", "code": 200}})
    raise AssertionError(f"unexpected GET {url}")

with patch.object(whatsapp, "WHATSAPP_ACCESS_TOKEN", "fake-token-wrong-waba"), \
     patch.object(whatsapp, "WHATSAPP_PHONE_NUMBER_ID", "551450234708715"), \
     patch.object(whatsapp, "WHATSAPP_WABA_ID", "453734811161130"), \
     patch("requests.get", side_effect=fake_get_perm_error):
    perm = whatsapp.whatsapp_subscription_check(apply=False)
assert perm["token_ok"] is False and any("Permission denied" in e for e in perm["errors"]), perm
print("PASS: token scoped to a different WABA -> token_ok:false, Meta's error surfaced")

# --- 5. The access token itself never appears anywhere in the JSON result ---
import json as _json
dump = _json.dumps(before) + _json.dumps(after) + _json.dumps(perm)
assert "fake-token" not in dump and "fake-token-wrong-waba" not in dump
print("PASS: access token never appears in the returned result")

print("\nALL WHATSAPP SUBSCRIPTION CHECK (006b) TESTS PASSED")
