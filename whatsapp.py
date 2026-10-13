import hashlib
import hmac
import logging
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from flask import Response, jsonify, request

from config import (
    META_APP_SECRET,
    PUBLIC_BASE_URL,
    WHATSAPP_ACCESS_TOKEN,
    WHATSAPP_API_VERSION,
    WHATSAPP_INBOUND_ALLOWLIST,
    WHATSAPP_INBOUND_ENABLED,
    WHATSAPP_PHONE_NUMBER_ID,
    WHATSAPP_RECIPIENT,
    WHATSAPP_REGISTRATION_PIN,
    WHATSAPP_VERIFY_TOKEN,
    WHATSAPP_WABA_ID,
)
from database import (
    connection, log_whatsapp_message, whatsapp_message_already_processed,
)
from public_site import site
from whatsapp_coexistence import META_APP_ID

log = logging.getLogger(__name__)


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


def _meta_graph_get(path: str, params: dict | None = None) -> tuple[dict, bool]:
    """GET helper for subscription_check - Authorization header (never the
    URL) so the token never lands in a server access log, unlike
    whatsapp_coexistence.py's onboarding-time calls which pass a short-lived
    code-exchange token as a request param. Returns (json_body, http_ok)."""
    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{path}"
    headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}
    try:
        response = requests.get(url, headers=headers, params=params or {}, timeout=20)
    except requests.RequestException as exc:
        return {"error": {"message": f"שגיאת תקשורת מול Meta: {exc}"}}, False
    try:
        data = response.json()
    except ValueError:
        data = {"error": {"message": f"Meta החזירה HTTP {response.status_code} ללא JSON"}}
    return (data if isinstance(data, dict) else {}), response.ok


def _meta_graph_post(path: str) -> tuple[dict, bool]:
    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{path}"
    headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}
    try:
        response = requests.post(url, headers=headers, timeout=20)
    except requests.RequestException as exc:
        return {"error": {"message": f"שגיאת תקשורת מול Meta: {exc}"}}, False
    try:
        data = response.json()
    except ValueError:
        data = {"error": {"message": f"Meta החזירה HTTP {response.status_code} ללא JSON"}}
    return (data if isinstance(data, dict) else {}), response.ok


def whatsapp_subscription_check(apply: bool = False) -> dict[str, Any]:
    """Task 006b: read-only (unless apply=True) check of whether this app is
    subscribed to the configured WABA's messages webhook - the most likely
    reason Meta never POSTs to /whatsapp-webhook despite every other setting
    looking correct. Never logs or returns WHATSAPP_ACCESS_TOKEN itself."""
    result: dict[str, Any] = {
        "phone": None,
        "waba_id": None,
        "subscribed": None,
        "subscribed_apps": None,
        "token_ok": True,
        "errors": [],
    }

    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        result["token_ok"] = False
        result["errors"].append(
            "WHATSAPP_ACCESS_TOKEN או WHATSAPP_PHONE_NUMBER_ID לא מוגדרים ב-Render."
        )
        return result

    phone_data, phone_ok = _meta_graph_get(
        WHATSAPP_PHONE_NUMBER_ID,
        {"fields": "id,display_phone_number,verified_name,quality_rating,platform_type,code_verification_status,status"},
    )
    if not phone_ok:
        result["token_ok"] = False
        result["errors"].append(_safe_meta_error_message(phone_data))
    else:
        display = str(phone_data.get("display_phone_number") or "")
        result["phone"] = {
            "id": phone_data.get("id"),
            "display_phone_number_ending": _digits_only(display)[-4:] if display else None,
            "verified_name": phone_data.get("verified_name"),
            "quality_rating": phone_data.get("quality_rating"),
            "platform_type": phone_data.get("platform_type"),
            "code_verification_status": phone_data.get("code_verification_status"),
            "status": phone_data.get("status"),
        }

    waba_id = WHATSAPP_WABA_ID or None
    if not waba_id and phone_ok:
        # Best-effort only - the phone-number node doesn't reliably expose
        # its parent WABA id as a plain field; WHATSAPP_WABA_ID is the
        # reliable source (see env.example).
        waba_id = phone_data.get("whatsapp_business_account_id") or None
    if not waba_id:
        result["errors"].append(
            "לא ידוע מזהה ה-WABA - צריך להוסיף WHATSAPP_WABA_ID ב-Render."
        )
        return result
    result["waba_id"] = waba_id

    sub_data, sub_ok = _meta_graph_get(f"{waba_id}/subscribed_apps")
    if not sub_ok:
        result["token_ok"] = False
        result["errors"].append(_safe_meta_error_message(sub_data))
        return result

    apps = sub_data.get("data") or []
    app_list = []
    for item in apps:
        api_data = item.get("whatsapp_business_api_data") if isinstance(item, dict) else None
        app_id = (api_data or {}).get("id") or (item or {}).get("id")
        app_name = (api_data or {}).get("name") or (item or {}).get("name")
        app_list.append({"id": app_id, "name": app_name})
    result["subscribed_apps"] = app_list
    result["subscribed"] = any(str(a.get("id")) == str(META_APP_ID) for a in app_list)

    if apply and not result["subscribed"]:
        apply_data, apply_ok = _meta_graph_post(f"{waba_id}/subscribed_apps")
        if not apply_ok:
            result["applied"] = False
            result["errors"].append(_safe_meta_error_message(apply_data))
            return result
        result["applied"] = True
        sub_data2, sub_ok2 = _meta_graph_get(f"{waba_id}/subscribed_apps")
        if sub_ok2:
            apps2 = sub_data2.get("data") or []
            app_list2 = []
            for item in apps2:
                api_data = item.get("whatsapp_business_api_data") if isinstance(item, dict) else None
                app_id = (api_data or {}).get("id") or (item or {}).get("id")
                app_name = (api_data or {}).get("name") or (item or {}).get("name")
                app_list2.append({"id": app_id, "name": app_name})
            result["subscribed_apps"] = app_list2
            result["subscribed"] = any(str(a.get("id")) == str(META_APP_ID) for a in app_list2)

    return result


def _safe_meta_error_message(data: dict) -> str:
    """Meta's bare error.message is often too generic to diagnose on its own
    (e.g. request_code's "Request code error" covers many different root
    causes) - append whatever extra diagnostic fields Meta did send
    (type/code/error_subcode/error_data.details/fbtrace_id), the same fields
    whatsapp_coexistence.py's _safe_meta_error already surfaces for the
    onboarding flow. Never includes WHATSAPP_ACCESS_TOKEN - it was never in
    this error object to begin with."""
    error = data.get("error") if isinstance(data, dict) else None
    if not isinstance(error, dict):
        return "Meta החזירה שגיאה לא ידועה."
    message = str(error.get("message") or "Meta החזירה שגיאה לא ידועה.")
    extra = []
    if error.get("type"):
        extra.append(f"type={error['type']}")
    if error.get("code") is not None:
        extra.append(f"code={error['code']}")
    if error.get("error_subcode") is not None:
        extra.append(f"subcode={error['error_subcode']}")
    details = (error.get("error_data") or {}).get("details") if isinstance(error.get("error_data"), dict) else None
    if details:
        extra.append(f"details={details}")
    if error.get("fbtrace_id"):
        extra.append(f"fbtrace_id={error['fbtrace_id']}")
    return f"{message} ({', '.join(extra)})" if extra else message


def _meta_graph_post_body(path: str, data: dict | None = None, json_body: dict | None = None) -> tuple[dict, bool]:
    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{path}"
    headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}
    try:
        response = requests.post(url, headers=headers, data=data, json=json_body, timeout=20)
    except requests.RequestException as exc:
        return {"error": {"message": f"שגיאת תקשורת מול Meta: {exc}"}}, False
    try:
        body = response.json()
    except ValueError:
        body = {"error": {"message": f"Meta החזירה HTTP {response.status_code} ללא JSON"}}
    return (body if isinstance(body, dict) else {}), response.ok


_STILL_LINKED_TO_APP_HINTS = (
    "already registered", "migrat", "linked to", "on-premise", "onprem", "coexistence",
)


def _maybe_add_still_linked_hint(errors: list, message: str) -> None:
    lower = message.lower()
    if any(hint in lower for hint in _STILL_LINKED_TO_APP_HINTS):
        errors.append("נראה שהמספר עדיין מקושר לאפליקציית WhatsApp Business בטלפון - צריך קודם למחוק משם את החשבון, ואז לנסות שוב.")


def whatsapp_request_code(method: str = "SMS", confirm: bool = False) -> dict[str, Any]:
    """Task 006c, step 1: Meta sends a verification code to the number by
    SMS or voice call - the first step of registering it directly on the
    Cloud API (no WhatsApp Business app / Coexistence). Without confirm=True
    this only explains what would happen - no call to Meta at all, since the
    business owner operates this from her phone and a stray tap must never
    trigger a real SMS."""
    method = (method or "SMS").strip().upper()
    if method not in ("SMS", "VOICE"):
        return {"ok": False, "errors": ["method חייב להיות SMS או VOICE."]}
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        return {"ok": False, "errors": ["WHATSAPP_ACCESS_TOKEN או WHATSAPP_PHONE_NUMBER_ID לא מוגדרים ב-Render."]}
    if not confirm:
        return {"ok": True, "would_send": True, "method": method, "errors": [],
                "message": f"לחיצה עם confirm=1 תשלח קוד אימות למספר דרך {method}. שום דבר לא נשלח כרגע."}

    data, ok = _meta_graph_post_body(f"{WHATSAPP_PHONE_NUMBER_ID}/request_code", data={"code_method": method, "language": "he"})
    if not ok:
        message = _safe_meta_error_message(data)
        errors = [message]
        _maybe_add_still_linked_hint(errors, message)
        return {"ok": False, "errors": errors}
    return {"ok": True, "sent": True, "method": method, "errors": []}


def whatsapp_verify_code(code: str, confirm: bool = False) -> dict[str, Any]:
    """Task 006c, step 2: confirm the code Meta sent in step 1."""
    digits = re.sub(r"\D", "", str(code or ""))
    if not digits:
        return {"ok": False, "errors": ["קוד האימות חסר."]}
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        return {"ok": False, "errors": ["WHATSAPP_ACCESS_TOKEN או WHATSAPP_PHONE_NUMBER_ID לא מוגדרים ב-Render."]}
    if not confirm:
        return {"ok": True, "would_verify": True, "errors": [],
                "message": "לחיצה עם confirm=1 תאמת את הקוד מול Meta. שום דבר לא נשלח כרגע."}

    data, ok = _meta_graph_post_body(f"{WHATSAPP_PHONE_NUMBER_ID}/verify_code", data={"code": digits})
    if not ok:
        message = _safe_meta_error_message(data)
        errors = [message]
        _maybe_add_still_linked_hint(errors, message)
        return {"ok": False, "errors": errors}
    return {"ok": True, "verified": True, "errors": []}


def whatsapp_register_number(confirm: bool = False) -> dict[str, Any]:
    """Task 006c, step 3: register the (now verified) number directly on the
    Cloud API using the business owner's own 2-step-verification PIN - the
    final step that makes WhatsApp actually deliver messages to our webhook
    instead of to the WhatsApp Business app. Never logs or returns the PIN
    or the access token."""
    if not WHATSAPP_REGISTRATION_PIN:
        return {"ok": False, "errors": ["WHATSAPP_REGISTRATION_PIN לא מוגדר ב-Render - צריך PIN בן 6 ספרות."]}
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        return {"ok": False, "errors": ["WHATSAPP_ACCESS_TOKEN או WHATSAPP_PHONE_NUMBER_ID לא מוגדרים ב-Render."]}
    if not confirm:
        return {"ok": True, "would_register": True, "errors": [],
                "message": "לחיצה עם confirm=1 תרשום את המספר ישירות ב-Cloud API. שום דבר לא נשלח כרגע."}

    data, ok = _meta_graph_post_body(
        f"{WHATSAPP_PHONE_NUMBER_ID}/register",
        json_body={"messaging_product": "whatsapp", "pin": WHATSAPP_REGISTRATION_PIN},
    )
    if not ok:
        message = _safe_meta_error_message(data)
        errors = [message]
        _maybe_add_still_linked_hint(errors, message)
        return {"ok": False, "errors": errors}

    result: dict[str, Any] = {"ok": True, "registered": True, "errors": []}
    phone_data, phone_ok = _meta_graph_get(
        WHATSAPP_PHONE_NUMBER_ID, {"fields": "status,platform_type,code_verification_status"}
    )
    if phone_ok:
        result["status"] = phone_data.get("status")
        result["platform_type"] = phone_data.get("platform_type")
        result["code_verification_status"] = phone_data.get("code_verification_status")
    return result


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

    # Task 006a: without META_APP_SECRET configured, a delivery can't be
    # verified at all - per spec, that means never processing it (log only),
    # not trusting it anyway.
    raw_body = request.get_data()
    if not META_APP_SECRET:
        log.warning("WhatsApp inbound webhook received but META_APP_SECRET is not configured - not processing.")
        return jsonify({"status": "received", "processed": False}), 200
    if not _verify_webhook_signature(raw_body, request.headers.get("X-Hub-Signature-256", "")):
        return Response("Forbidden", status=403, mimetype="text/plain")

    # Meta expects a fast HTTP 200 acknowledgement - the actual reply (one or
    # more Claude calls, a possible flight/lodging/car search trigger) can
    # take real seconds, so it happens in a background thread instead of
    # blocking this response.
    payload = request.get_json(silent=True) or {}
    threading.Thread(target=_process_webhook_payload, args=(payload,), daemon=True, name="whatsapp-inbound").start()
    return jsonify({"status": "received", "object": payload.get("object")}), 200


def _verify_webhook_signature(raw_body: bytes, signature_header: str) -> bool:
    if not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(META_APP_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    provided = signature_header[len("sha256="):]
    return hmac.compare_digest(expected, provided)


_ALLOWLIST_REPLY_WINDOW_HOURS = 24
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_WHATSAPP_MESSAGE_LIMIT = 4000


def _adapt_text_for_whatsapp(text: str) -> str:
    """HTML (never expected from Tinkerbell, but defensive) is stripped;
    markdown bold **like this** becomes WhatsApp's *like this*. An empty
    reply gets the same fallback line the website uses for its own empty
    replies."""
    text = _HTML_TAG_RE.sub("", str(text or ""))
    text = _BOLD_RE.sub(r"*\1*", text)
    return text.strip() or "אני איתכם 😊"


def _split_for_whatsapp(text: str, limit: int = _WHATSAPP_MESSAGE_LIMIT) -> list[str]:
    """Split on paragraph boundaries first (so a long reply stays readable
    across several messages, sent in order); a single paragraph still over
    the limit is hard-split as a last resort."""
    if len(text) <= limit:
        return [text]
    chunks = []
    current = ""
    for para in text.split("\n\n"):
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) > limit and current:
            chunks.append(current)
            current = para
        else:
            current = candidate
    if current:
        chunks.append(current)
    final = []
    for chunk in chunks:
        while len(chunk) > limit:
            final.append(chunk[:limit])
            chunk = chunk[limit:]
        if chunk:
            final.append(chunk)
    return final


def _phone_hash_for_log(phone: str) -> str:
    from nova_conversation import _phone_hash
    return _phone_hash(phone)


def _member_id_for_log(phone: str) -> int | None:
    from nova_conversation import linked_member_for_phone, registered_member_for_phone
    try:
        return linked_member_for_phone(phone) or registered_member_for_phone(phone)
    except Exception:
        return None


def _reply_and_log(phone: str, phone_hash_val: str, text: str) -> None:
    member_id = _member_id_for_log(phone)
    for chunk in _split_for_whatsapp(_adapt_text_for_whatsapp(text)):
        try:
            result = send_text_message(chunk, recipient=phone)
            log_whatsapp_message(result.get("message_id"), phone_hash_val, member_id, "out", "text", chunk, None, "sent")
        except (WhatsAppConfigurationError, WhatsAppSendError) as exc:
            log_whatsapp_message(None, phone_hash_val, member_id, "out", "text", chunk, None, "send_failed", str(exc))
            log.error("WhatsApp send failed to ...%s: %s", _digits_only(phone)[-4:], exc)


def _is_allowlisted(phone: str) -> bool:
    from nova_conversation import canonical_phone
    canonical = canonical_phone(phone)
    if not canonical:
        return False
    return canonical in {canonical_phone(p) for p in WHATSAPP_INBOUND_ALLOWLIST}


def _reply_not_allowlisted(phone: str, phone_hash_val: str, wa_message_id: str, msg_type: str) -> None:
    """At most one "coming soon" reply per number per day - never Ariella
    herself, and never more than the one courtesy line."""
    with connection() as conn:
        row = conn.execute(
            "SELECT created_at FROM whatsapp_inbound_log WHERE phone_hash=? AND status='ignored_not_allowlisted' ORDER BY id DESC LIMIT 1",
            (phone_hash_val,),
        ).fetchone()
    already_told_recently = False
    if row:
        try:
            last = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            already_told_recently = (datetime.now(timezone.utc) - last) < timedelta(hours=_ALLOWLIST_REPLY_WINDOW_HOURS)
        except Exception:
            already_told_recently = False
    log_whatsapp_message(wa_message_id, phone_hash_val, None, "in", msg_type, None, None, "ignored_not_allowlisted")
    if already_told_recently:
        return
    site_link = f"{PUBLIC_BASE_URL}" if PUBLIC_BASE_URL else ""
    message = f"היי 🌷 אריאלה בוואטסאפ תיפתח בקרוב. בינתיים אפשר לתכנן איתה חופשה באתר{': ' + site_link if site_link else ''}."
    _reply_and_log(phone, phone_hash_val, message)


def _extract_button_payload(message: dict) -> str | None:
    button = message.get("button")
    if isinstance(button, dict) and button.get("payload"):
        return str(button["payload"])
    interactive = message.get("interactive") or {}
    button_reply = interactive.get("button_reply")
    if isinstance(button_reply, dict) and button_reply.get("id"):
        return str(button_reply["id"])
    list_reply = interactive.get("list_reply")
    if isinstance(list_reply, dict) and list_reply.get("id"):
        return str(list_reply["id"])
    return None


def _process_one_message(message: dict, profile_name: str) -> None:
    wa_message_id = str(message.get("id") or "")
    phone = str(message.get("from") or "")
    if not phone:
        return
    phone_hash_val = _phone_hash_for_log(phone)
    msg_type = str(message.get("type") or "")

    if whatsapp_message_already_processed(wa_message_id):
        return

    if not WHATSAPP_INBOUND_ENABLED:
        log_whatsapp_message(wa_message_id, phone_hash_val, None, "in", msg_type, None, None, "ignored_disabled")
        return

    if not _is_allowlisted(phone):
        _reply_not_allowlisted(phone, phone_hash_val, wa_message_id, msg_type)
        return

    button_payload = _extract_button_payload(message)
    text = str((message.get("text") or {}).get("body") or "") if msg_type == "text" else ""

    if msg_type not in ("text", "button", "interactive"):
        log_whatsapp_message(wa_message_id, phone_hash_val, _member_id_for_log(phone), "in", msg_type, None, button_payload, "received")
        _reply_and_log(phone, phone_hash_val, "כרגע אני קוראת רק הודעות טקסט 🙏 אפשר לכתוב לי במילים?")
        return

    log_whatsapp_message(wa_message_id, phone_hash_val, _member_id_for_log(phone), "in", msg_type, text, button_payload, "received")

    from nova_conversation import route_inbound
    try:
        reply = route_inbound(phone, text, profile_name=profile_name, button_payload=button_payload)
    except Exception:
        log.exception("WhatsApp inbound: route_inbound failed")
        reply = "קרתה תקלה זמנית, ננסה שוב בעוד רגע 🙏"

    _reply_and_log(phone, phone_hash_val, reply)


def _process_change_value(value: dict) -> None:
    contacts = value.get("contacts") or []
    profile_name = ""
    if contacts and isinstance(contacts[0], dict):
        profile_name = str((contacts[0].get("profile") or {}).get("name") or "")[:120]
    for message in value.get("messages") or []:
        try:
            _process_one_message(message, profile_name)
        except Exception:
            log.exception("WhatsApp inbound: failed to process one message")
    # Delivery/read receipts - logged, never treated as a message to answer.
    for status in value.get("statuses") or []:
        log.info("WhatsApp delivery status: %s", (status or {}).get("status"))


def _process_webhook_payload(payload: dict) -> None:
    try:
        for entry in payload.get("entry") or []:
            for change in entry.get("changes") or []:
                _process_change_value(change.get("value") or {})
    except Exception:
        log.exception("WhatsApp inbound webhook processing failed")


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
