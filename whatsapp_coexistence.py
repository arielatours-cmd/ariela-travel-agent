import os

import requests
from flask import Blueprint, jsonify, render_template, request, redirect, url_for

whatsapp_coexistence = Blueprint("whatsapp_coexistence", __name__)

META_APP_ID = "919805650390657"
META_GRAPH_VERSION = "v24.0"


@whatsapp_coexistence.get("/whatsapp-coexistence-setup")
def setup():
    return render_template(
        "whatsapp_coexistence_setup.html",
        meta_app_id=META_APP_ID,
    )


@whatsapp_coexistence.post("/whatsapp-coexistence/exchange-code")
def exchange_code():
    """Exchange the Embedded Signup authorization code on the server."""
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

    # WhatsApp Embedded Signup returns a one-time code via FB.login().
    # Exchange that code directly for the business token. Do not send a
    # redirect_uri here: Embedded Signup's token exchange only requires the
    # app ID, app secret and authorization code.
    exchange_params = {
        "client_id": META_APP_ID,
        "client_secret": app_secret,
        "code": code,
    }

    try:
        response = requests.get(
            f"https://graph.facebook.com/{META_GRAPH_VERSION}/oauth/access_token",
            params=exchange_params,
            timeout=20,
        )
        data = response.json()
    except requests.RequestException as exc:
        return jsonify({
            "ok": False,
            "error": "meta_request_failed",
            "message": str(exc),
        }), 502
    except ValueError:
        return jsonify({
            "ok": False,
            "error": "meta_invalid_response",
            "status_code": response.status_code,
        }), 502

    if not response.ok or not data.get("access_token"):
        safe_error = data.get("error", data)
        return jsonify({
            "ok": False,
            "error": "meta_code_exchange_failed",
            "meta": safe_error,
        }), 400

    # Never return the access token to the browser.
    return jsonify({
        "ok": True,
        "connected": True,
        "token_received": True,
        "expires_in": data.get("expires_in"),
        "session_info": session_info,
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
