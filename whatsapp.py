import re
from typing import Any

import requests
from flask import Response, jsonify, request

from config import (
    WHATSAPP_ACCESS_TOKEN,
    WHATSAPP_API_VERSION,
    WHATSAPP_PHONE_NUMBER_ID,
    WHATSAPP_RECIPIENT,
    WHATSAPP_VERIFY_TOKEN,
)
from public_site import site


class WhatsAppConfigurationError(RuntimeError):
    pass


class WhatsAppSendError(RuntimeError):
    pass


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def whatsapp_status() -> dict[str, Any]:
    missing = []
    if not WHATSAPP_ACCESS_TOKEN:
        missing.append("WHATSAPP_ACCESS_TOKEN")
    if not WHATSAPP_PHONE_NUMBER_ID:
        missing.append("WHATSAPP_PHONE_NUMBER_ID")
    if not WHATSAPP_RECIPIENT:
        missing.append("WHATSAPP_RECIPIENT")

    return {
        "configured": not missing,
        "missing": missing,
        "api_version": WHATSAPP_API_VERSION,
        "phone_number_id_configured": bool(WHATSAPP_PHONE_NUMBER_ID),
        "recipient_configured": bool(WHATSAPP_RECIPIENT),
        "recipient_ending": _digits_only(WHATSAPP_RECIPIENT)[-4:] if WHATSAPP_RECIPIENT else None,
        "access_token_configured": bool(WHATSAPP_ACCESS_TOKEN),
        "verify_token_configured": bool(WHATSAPP_VERIFY_TOKEN),
    }


def _require_configuration() -> None:
    status = whatsapp_status()
    if not status["configured"]:
        raise WhatsAppConfigurationError(
            "חסרים משתני סביבה ב-Render: " + ", ".join(status["missing"])
        )


@site.route("/whatsapp-webhook", methods=["GET", "POST"])
def whatsapp_webhook():
    if request.method == "GET":
        mode = request.args.get("hub.mode", "")
        token = request.args.get("hub.verify_token", "")
        challenge = request.args.get("hub.challenge", "")

        if (
            mode == "subscribe"
            and WHATSAPP_VERIFY_TOKEN
            and token == WHATSAPP_VERIFY_TOKEN
        ):
            return Response(challenge, status=200, mimetype="text/plain")

        return Response("Forbidden", status=403, mimetype="text/plain")

    # Meta expects a fast HTTP 200 acknowledgement for webhook deliveries.
    # Inbound message routing will be handled in the next WhatsApp integration phase.
    payload = request.get_json(silent=True) or {}
    return jsonify({"status": "received", "object": payload.get("object")}), 200


def send_text_message(message: str, recipient: str | None = None) -> dict[str, Any]:
    _require_configuration()

    text = (message or "").strip()
    if not text:
        raise WhatsAppSendError("אין תוכן לשליחה.")

    to_number = _digits_only(recipient or WHATSAPP_RECIPIENT)
    if not to_number:
        raise WhatsAppConfigurationError("מספר הנמען אינו תקין.")

    url = (
        f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/"
        f"{WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": "text",
        "text": {"preview_url": True, "body": text},
    }
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
    except requests.RequestException as exc:
        raise WhatsAppSendError(f"שגיאת תקשורת מול Meta: {exc}") from exc

    try:
        data = response.json()
    except ValueError:
        data = {"raw_response": response.text[:1000]}

    if not response.ok:
        error = data.get("error") if isinstance(data, dict) else None
        message_text = (
            error.get("message")
            if isinstance(error, dict) and error.get("message")
            else f"Meta החזירה HTTP {response.status_code}"
        )
        raise WhatsAppSendError(message_text)

    message_id = None
    if isinstance(data, dict):
        messages = data.get("messages") or []
        if messages and isinstance(messages[0], dict):
            message_id = messages[0].get("id")

    return {
        "status": "success",
        "message_id": message_id,
        "recipient_ending": to_number[-4:],
        "meta_response": data,
    }


def send_template_message(
    recipient: str, template_name: str, body_params: list[str] | None = None,
    buttons: list[dict] | None = None, language_code: str = "he",
) -> dict[str, Any]:
    """Send an approved WhatsApp template message with optional quick-reply
    buttons (payload: {"text": ..., "payload": ...} per button, matching
    build_daily_whatsapp_payload's shape). Ready for when the welcome/daily-
    deals templates are approved in Meta - not called anywhere yet while
    WHATSAPP_DEALS_BUTTONS_ENABLED stays false (task 003a)."""
    _require_configuration()

    name = (template_name or "").strip()
    if not name:
        raise WhatsAppSendError("חסר שם תבנית.")

    to_number = _digits_only(recipient or WHATSAPP_RECIPIENT)
    if not to_number:
        raise WhatsAppConfigurationError("מספר הנמען אינו תקין.")

    components = []
    if body_params:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": str(p)} for p in body_params],
        })
    for index, button in enumerate(buttons or []):
        payload = str((button or {}).get("payload") or "")
        if not payload:
            continue
        components.append({
            "type": "button",
            "sub_type": "quick_reply",
            "index": str(index),
            "parameters": [{"type": "payload", "payload": payload}],
        })

    url = (
        f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/"
        f"{WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    payload_body = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": "template",
        "template": {
            "name": name,
            "language": {"code": language_code},
            "components": components,
        },
    }
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, json=payload_body, timeout=30)
    except requests.RequestException as exc:
        raise WhatsAppSendError(f"שגיאת תקשורת מול Meta: {exc}") from exc

    try:
        data = response.json()
    except ValueError:
        data = {"raw_response": response.text[:1000]}

    if not response.ok:
        error = data.get("error") if isinstance(data, dict) else None
        message_text = (
            error.get("message")
            if isinstance(error, dict) and error.get("message")
            else f"Meta החזירה HTTP {response.status_code}"
        )
        raise WhatsAppSendError(message_text)

    message_id = None
    if isinstance(data, dict):
        messages = data.get("messages") or []
        if messages and isinstance(messages[0], dict):
            message_id = messages[0].get("id")

    return {
        "status": "success",
        "message_id": message_id,
        "recipient_ending": to_number[-4:],
        "meta_response": data,
    }
