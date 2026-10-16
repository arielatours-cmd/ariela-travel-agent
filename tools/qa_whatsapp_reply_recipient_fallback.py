"""QA for a live bug found by Shlomo while testing with Meta's WhatsApp test
number (15.10.2026, 17:15 UTC): the webhook received an inbound message and
Ariella tried to reply, but the send failed with "חסרים משתני סביבה
ב-Render: WHATSAPP_RECIPIENT" - even though an explicit recipient (the real
sender's phone) was being passed to send_text_message.

Root cause: _require_configuration() always demanded WHATSAPP_RECIPIENT via
whatsapp_status(), regardless of whether a recipient was explicitly given.
WHATSAPP_RECIPIENT is only a fallback default for an admin test-send with no
explicit recipient (app.py's /admin/send-whatsapp-test, or similar) - it must
never block a real reply to an inbound sender.

Fixed: _require_configuration(recipient=None) only requires WHATSAPP_RECIPIENT
when no explicit recipient was passed in. Both send_text_message and
send_template_message now pass their recipient through.

Run: python3 tools/qa_whatsapp_reply_recipient_fallback.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import whatsapp
whatsapp.WHATSAPP_ACCESS_TOKEN = "test-token"
whatsapp.WHATSAPP_PHONE_NUMBER_ID = "123456"
whatsapp.WHATSAPP_RECIPIENT = ""  # deliberately unset, like the live bug

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# --- 1. The exact live bug: an explicit recipient (a real inbound sender's
#        phone) must never be blocked by an unset WHATSAPP_RECIPIENT ---
try:
    whatsapp._require_configuration("972501234567")
    check("explicit recipient bypasses the WHATSAPP_RECIPIENT requirement", True)
except whatsapp.WhatsAppConfigurationError as exc:
    check(f"explicit recipient bypasses the WHATSAPP_RECIPIENT requirement (got: {exc})", False)

# --- 2. Regression guard: an admin test-send with NO explicit recipient
#        still correctly requires WHATSAPP_RECIPIENT as its fallback default ---
try:
    whatsapp._require_configuration(None)
    check("no recipient at all still requires WHATSAPP_RECIPIENT", False)
except whatsapp.WhatsAppConfigurationError as exc:
    check("no recipient at all still requires WHATSAPP_RECIPIENT", "WHATSAPP_RECIPIENT" in str(exc))

try:
    whatsapp._require_configuration()
    check("no recipient argument at all (default) still requires WHATSAPP_RECIPIENT", False)
except whatsapp.WhatsAppConfigurationError as exc:
    check("no recipient argument at all (default) still requires WHATSAPP_RECIPIENT", "WHATSAPP_RECIPIENT" in str(exc))

# --- 3. Regression guard: the truly required vars are still enforced
#        regardless of recipient ---
whatsapp.WHATSAPP_ACCESS_TOKEN = ""
try:
    whatsapp._require_configuration("972501234567")
    check("missing WHATSAPP_ACCESS_TOKEN still blocks even with an explicit recipient", False)
except whatsapp.WhatsAppConfigurationError as exc:
    check("missing WHATSAPP_ACCESS_TOKEN still blocks even with an explicit recipient",
          "WHATSAPP_ACCESS_TOKEN" in str(exc))
whatsapp.WHATSAPP_ACCESS_TOKEN = "test-token"

whatsapp.WHATSAPP_PHONE_NUMBER_ID = ""
try:
    whatsapp._require_configuration("972501234567")
    check("missing WHATSAPP_PHONE_NUMBER_ID still blocks even with an explicit recipient", False)
except whatsapp.WhatsAppConfigurationError as exc:
    check("missing WHATSAPP_PHONE_NUMBER_ID still blocks even with an explicit recipient",
          "WHATSAPP_PHONE_NUMBER_ID" in str(exc))
whatsapp.WHATSAPP_PHONE_NUMBER_ID = "123456"

# --- 4. whatsapp_status() (used for /health and /admin diagnostics) is
#        unchanged - still reports WHATSAPP_RECIPIENT as missing either way,
#        since it's a general-purpose configuration snapshot, not a gate ---
status = whatsapp.whatsapp_status()
check("whatsapp_status() still flags WHATSAPP_RECIPIENT as missing (diagnostics unaffected)",
      "WHATSAPP_RECIPIENT" in status["missing"] and status["configured"] is False)

# --- 5. Both real send functions forward their recipient into the gate ---
import inspect
send_text_src = inspect.getsource(whatsapp.send_text_message)
send_template_src = inspect.getsource(whatsapp.send_template_message)
check("send_text_message passes its recipient into _require_configuration",
      "_require_configuration(recipient)" in send_text_src)
check("send_template_message passes its recipient into _require_configuration",
      "_require_configuration(recipient)" in send_template_src)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL WHATSAPP-REPLY-RECIPIENT-FALLBACK TESTS PASSED")
