import os

import requests
from flask import Blueprint, jsonify, render_template, request

whatsapp_coexistence = Blueprint("whatsapp_coexistence", __name__)

META_APP_ID = "919805650390657"
META_GRAPH_VERSION = "v24.0"
META_OAUTH_REDIRECT_URI = "https://ariela-travel-agent.onrender.com/facebook/callback"


@whatsapp_coexistence.get("/whatsapp-coexistence-setup")
def setup():
    return render_template(
        "whatsapp_coexistence_setup.html",
        meta_app_id=META_APP_ID,
        meta_redirect_uri=META_OAUTH_REDIRECT_URI,
    )


def _meta_json(response):
    try:
        return response.json()
    except ValueError:
        return {"error": {"message": "Meta returned a non-JSON response"}}


def _safe_meta_error(data):
    raw = data.get("error", data) if isinstance(data, dict) else {}
    if not isinstance(raw, dict):
        return {"message": str(raw)[:500]}
    allowed = (
        "message", "type", "code", "error_subcode",
        "error_user_title", "error_user_msg",
    )
    safe = {key: raw.get(key) for key in allowed if raw.get(key) is not None}
    if not safe:
        safe["message"] = "Meta returned an OAuth error without readable details."
    return safe


@whatsapp_coexistence.post("/whatsapp-coexistence/exchange-code")
def exchange_code():
    payload = request.get_json(silent=True) or {}
    code = payload.get("code")
    session_info = payload.get("session_info") or {}

    if not code:
        return jsonify({"ok": False, "error": "missing_code"}), 400

    app_secret = os.getenv("META_APP_SECRET")
    if not app_secret:
        return jsonify({
            "ok": False,
            "error": "missing_meta_app_secret",
            "message": "META_APP_SECRET is not configured on the server."
        }), 500

    exchange_data = {
        "client_id": META_APP_ID,
        "client_secret": app_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": META_OAUTH_REDIRECT_URI,
    }

    try:
        response = requests.post(
            f"https://graph.facebook.com/{META_GRAPH_VERSION}/oauth/access_token",
            data=exchange_data,
            timeout=20,
        )
    except requests.RequestException as exc:
        return jsonify({
            "ok": False,
            "error": "meta_request_failed",
            "message": str(exc),
        }), 502

    data = _meta_json(response)
    access_token = data.get("access_token") if isinstance(data, dict) else None
    if not response.ok or not access_token:
        safe_error = _safe_meta_error(data)
        print(
            "WhatsApp coexistence token exchange failed: "
            f"status={response.status_code} meta={safe_error}"
        )
        return jsonify({
            "ok": False,
            "error": "meta_code_exchange_failed",
            "message": safe_error.get("message"),
            "meta": safe_error,
            "http_status": response.status_code,
        }), 400

    waba_id = session_info.get("waba_id")
    phone_number_id = session_info.get("phone_number_id")
    phone = None
    subscribed = False

    if waba_id:
        try:
            sub_response = requests.post(
                f"https://graph.facebook.com/{META_GRAPH_VERSION}/{waba_id}/subscribed_apps",
                data={"access_token": access_token},
                timeout=20,
            )
            subscribed = sub_response.ok

            phone_response = requests.get(
                f"https://graph.facebook.com/{META_GRAPH_VERSION}/{waba_id}/phone_numbers",
                params={
                    "access_token": access_token,
                    "fields": "id,display_phone_number,verified_name",
                },
                timeout=20,
            )
            phone_data = _meta_json(phone_response)
            phones = phone_data.get("data") or []
            if phones:
                if phone_number_id:
                    phone = next(
                        (item for item in phones if str(item.get("id")) == str(phone_number_id)),
                        phones[0],
                    )
                else:
                    phone = phones[0]
                    phone_number_id = phone.get("id")
        except requests.RequestException:
            pass

    return jsonify({
        "ok": True,
        "connected": True,
        "token_received": True,
        "expires_in": data.get("expires_in"),
        "waba_id": waba_id,
        "phone_number_id": phone_number_id,
        "webhooks_subscribed": subscribed,
        "phone": {
            "id": phone.get("id"),
            "display_phone_number": phone.get("display_phone_number"),
            "verified_name": phone.get("verified_name"),
        } if phone else None,
    })


@whatsapp_coexistence.get("/facebook/callback")
def facebook_callback():
    return "Meta callback ready", 200
