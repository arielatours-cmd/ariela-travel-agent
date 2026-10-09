"""WhatsApp deals welcome message + stop-button wiring (task 003a).

Nothing here sends a real WhatsApp message. Every message is written to
whatsapp_outbound_queue in 'preview' status; actual sending (via
whatsapp.send_template_message) only happens once WHATSAPP_DEALS_BUTTONS_
ENABLED is true AND the welcome/daily-deals templates are approved in Meta -
neither is true yet, so this module only ever queues/previews.
"""
from database import connection, utc_now_iso, set_whatsapp_deals_opt, queue_whatsapp_message

WELCOME_BUTTON_TEXT = "הפסקת הדילים"
WELCOME_BUTTON_PAYLOAD = "STOP_HOT_DEALS"


def _welcome_message_body() -> str:
    return (
        "🎉 *איזה כיף שהצטרפתם!*\n"
        "מעכשיו, פעם ביום, אריאלה תשלח לכם לכאן את הדילים הכי שווים שמצאה - "
        "טיסות מנתב\"ג במחיר אמיתי, כולל מזוודה.\n"
        "✈️ הדילים מגיעים כל יום, חוץ משבת.\n"
        "💬 ובכל רגע אפשר פשוט לכתוב לאריאלה ולתכנן חופשה.\n"
        "רוצים להפסיק? לחיצה אחת על הכפתור למטה 👇"
    )


def queue_whatsapp_welcome(member_id: int) -> int | None:
    """Queues the welcome message for this member unless it was already
    sent since their most recent opt-in (so re-joining after a stop sends a
    fresh welcome, but a duplicate payment confirmation for the same opt-in
    never sends it twice). Returns the new queue row id, or None if skipped."""
    with connection() as conn:
        row = conn.execute(
            "SELECT whatsapp_opt_in_at, whatsapp_welcome_sent_at FROM members WHERE id=?",
            (member_id,),
        ).fetchone()
        if not row:
            return None
        opt_in_at = row["whatsapp_opt_in_at"]
        welcome_sent_at = row["whatsapp_welcome_sent_at"]
        already_sent_for_this_opt_in = bool(
            welcome_sent_at and opt_in_at and welcome_sent_at >= opt_in_at
        )
        if already_sent_for_this_opt_in:
            return None
        queue_id = queue_whatsapp_message(
            member_id, "welcome", _welcome_message_body(),
            buttons=[{"text": WELCOME_BUTTON_TEXT, "payload": WELCOME_BUTTON_PAYLOAD}],
        )
        conn.execute(
            "UPDATE members SET whatsapp_welcome_sent_at=? WHERE id=?",
            (utc_now_iso(), member_id),
        )
        conn.commit()
    return queue_id


def on_whatsapp_deals_paid(member_id: int) -> bool:
    """The one place a whatsapp_deals_9 payment confirmation turns into an
    active opt-in + welcome message. Mirrors _confirm_paid_search's role for
    the 19/39 ILS personal-search products: today reachable only from the
    admin manual-confirm action (no live payment processor yet); a real
    gateway's webhook will call this same function once it exists."""
    changed = set_whatsapp_deals_opt(member_id, True, "payment")
    queue_whatsapp_welcome(member_id)
    return changed
