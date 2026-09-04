from flask import Blueprint, render_template, request, redirect, url_for

whatsapp_coexistence = Blueprint("whatsapp_coexistence", __name__)


@whatsapp_coexistence.get("/whatsapp-coexistence-setup")
def setup():
    return render_template(
        "whatsapp_coexistence_setup.html",
        meta_app_id="919805650390657",
    )


@whatsapp_coexistence.get("/facebook/callback")
def facebook_callback():
    """OAuth return endpoint for Meta/Facebook Login for Business.

    Embedded Signup normally returns its authorization code to the JS SDK. This
    endpoint also gives Meta a stable HTTPS redirect URI for browser-based/mobile
    OAuth returns and sends the user back to the WhatsApp onboarding page.
    """
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
