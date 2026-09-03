from flask import Blueprint, render_template

whatsapp_coexistence = Blueprint("whatsapp_coexistence", __name__)


@whatsapp_coexistence.get("/whatsapp-coexistence-setup")
def setup():
    return render_template(
        "whatsapp_coexistence_setup.html",
        meta_app_id="919805650390657",
    )
