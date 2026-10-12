"""Outbound transactional email via Gmail SMTP (or any SMTP-compatible
provider) - starts with password-reset emails, reusable for anything else
that needs to reach a customer's inbox later.

Configured via MAIL_USERNAME/MAIL_APP_PASSWORD/MAIL_SMTP_HOST/MAIL_SMTP_PORT
(config.py, already used by the feedback-form setup doc). MAIL_APP_PASSWORD
is a Google "App Password" (16 characters, generated under the Gmail
account's own Security settings, only available once 2-Step Verification is
turned on for that account) - never the account's real login password,
which Gmail's SMTP rejects outright for third-party apps.

Never raises: every public function here returns True/False and logs on
failure, so a broken mail provider can never turn into a 500 for the
customer-facing route that called it.
"""
import logging
import smtplib
import ssl
from email.message import EmailMessage

from config import MAIL_USERNAME, MAIL_APP_PASSWORD, MAIL_SMTP_HOST, MAIL_SMTP_PORT

log = logging.getLogger(__name__)


def mail_configured() -> bool:
    return bool(MAIL_USERNAME and MAIL_APP_PASSWORD)


def mail_check(test_to: str | None = None) -> dict:
    """Read-only (plus one optional real send) diagnostic for /admin/mail-check
    - mirrors the live-debugging pattern already used for CJ
    (partner_commissions.cj_connection_check): report the config this
    process actually sees (never the raw app password) and, if a recipient
    is given, attempt one real send and surface the exact exception instead
    of only a logged one, since send_email() itself never raises."""
    result = {
        "configured": mail_configured(),
        "username": MAIL_USERNAME or None,
        "app_password_len": len(MAIL_APP_PASSWORD) if MAIL_APP_PASSWORD else 0,
        "smtp_host": MAIL_SMTP_HOST,
        "smtp_port": MAIL_SMTP_PORT,
    }
    if test_to:
        if not result["configured"]:
            result["send_attempted"] = False
            result["send_error"] = "MAIL_USERNAME/MAIL_APP_PASSWORD not configured"
            return result
        result["send_attempted"] = True
        try:
            context = ssl.create_default_context()
            port = int(MAIL_SMTP_PORT)
            msg = EmailMessage()
            msg["Subject"] = "Ariela mail-check test"
            msg["From"] = MAIL_USERNAME
            msg["To"] = test_to
            msg.set_content("This is a test email from /admin/mail-check.")
            if port == 465:
                with smtplib.SMTP_SSL(MAIL_SMTP_HOST, port, context=context, timeout=20) as server:
                    server.login(MAIL_USERNAME, MAIL_APP_PASSWORD)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(MAIL_SMTP_HOST, port, timeout=20) as server:
                    server.starttls(context=context)
                    server.login(MAIL_USERNAME, MAIL_APP_PASSWORD)
                    server.send_message(msg)
            result["send_ok"] = True
        except Exception as exc:
            result["send_ok"] = False
            result["send_error"] = f"{type(exc).__name__}: {exc}"
    return result


def send_email(to: str, subject: str, body_text: str, body_html: str | None = None) -> bool:
    """Returns True only once the SMTP server has accepted the message for
    delivery - never a guarantee of inbox delivery, just of a successful
    handoff. False (logged) for any failure: not configured, a bad
    recipient, or an SMTP/network error."""
    if not mail_configured():
        log.warning("send_email: MAIL_USERNAME/MAIL_APP_PASSWORD not configured - not sending to %s", to)
        return False
    to = str(to or "").strip()
    if not to or "@" not in to:
        log.warning("send_email: invalid recipient %r", to)
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = MAIL_USERNAME
    msg["To"] = to
    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")

    try:
        context = ssl.create_default_context()
        port = int(MAIL_SMTP_PORT)
        if port == 465:
            with smtplib.SMTP_SSL(MAIL_SMTP_HOST, port, context=context, timeout=20) as server:
                server.login(MAIL_USERNAME, MAIL_APP_PASSWORD)
                server.send_message(msg)
        else:
            with smtplib.SMTP(MAIL_SMTP_HOST, port, timeout=20) as server:
                server.starttls(context=context)
                server.login(MAIL_USERNAME, MAIL_APP_PASSWORD)
                server.send_message(msg)
        return True
    except Exception:
        log.exception("send_email failed to %s", to)
        return False
