import os

import requests
from flask import Blueprint, jsonify, render_template, request, redirect, url_for

whatsapp_coexistence = Blueprint("whatsapp_coexistence", __name__)

META_APP_ID = "919805650390657"
META_GRAPH_VERSION = "v24.0"
EMBEDDED_SIGNUP_REDIRECT_URI = "https://ariela-travel-agent.onrender.com/whatsapp-coexistence-setup"


@whatsapp_coexistence.get("/whatsapp-coexistence-setup")
def setup():
    return render_template(
        "whatsapp_coexistence_setup.html",
        meta_app_id=META_APP_ID,
    )


def _meta_json(response):
    try:
        return response.json()
    except ValueError:
        return {"error": {"message": "Meta returned a non-JSON response"}}


@whatsapp_coexistence.post("/whatsapp-coexistence/exchange-code")
def exchange_code():
    """Exchange the Embedded Signup code and finish safe server-side setup.

    Coexistence numbers are already registered in the WhatsApp Business app, so
    this endpoint deliberately does not call the phone-number /register endpoint.
    """
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

    exchange_params = {
        "client_id": META_APP_ID,
        "client_secret": app_secret,
        "code": code,
        "redirect_uri": EMBEDDED_SIGNUP_REDIRECT_URI,
    }

    try:
        response = requests.get(
            f"https://graph.facebook.com/{META_GRAPH_VERSION}/oauth/access_token",
            params=exchange_params,
            timeout=20,
        )
    except requests.RequestException as exc:
        return jsonify({
            "ok": False,
            "error": "meta_request_failed",
            "message": str(exc),
        }), 502

    data = _meta_json(response)
    access_token = data.get("access_token")
    if not response.ok or not access_token:
        safe_error = data.get("error", data)
        return jsonify({
            "ok": False,
            "error": "meta_code_exchange_failed",
            "meta": safe_error,
        }), 400

    waba_id = session_info.get("waba_id")
    phone_number_id = session_info.get("phone_number_id")
    phone = None
    subscribed = False

    # If Meta supplied the WABA in the FINISH event, subscribe this app to its
    # webhooks and discover the actual phone-number object. No token is ever
    # returned to the browser.
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
            # The OAuth exchange itself succeeded. Discovery/subscription can be
            # retried separately, so do not expose the access token or fail the
            # entire onboarding response here.
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
    """OAuth return endpoint for Meta/Facebook Login for Business."""
    error = request.args.get("error") or request.args.get("error_reason")
    code = request.args.get("code")
    state = request.args.get("state")

    if error:
        return redirect(url_for("whatsapp_coexistence.setup", meta_error=error))

    params = {}
    if code:
        params["meta_code"] = code
    if state:
        params["meta_state"] = state
    params["meta_callback"] = "1"
    return redirect(url_for("whatsapp_coexistence.setup", **params))
