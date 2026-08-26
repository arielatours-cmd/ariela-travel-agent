"""NOVA WhatsApp handoff helpers (Phase N1).

The handoff never exposes a member id. A short-lived opaque code is signed with
HMAC, stored only as a SHA-256 hash, and can be consumed exactly once when the
WhatsApp webhook confirms the sender identity in a later phase.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from config import FLASK_SECRET_KEY, NOVA_HANDOFF_TTL_MINUTES, WHATSAPP_BUSINESS_NUMBER
from database import connection, utc_now_iso


class NovaHandoffError(RuntimeError):
    pass


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _secret_bytes() -> bytes:
    secret = (FLASK_SECRET_KEY or "").strip()
    if not secret or secret == "change-this-before-production":
        raise NovaHandoffError("FLASK_SECRET_KEY אינו מוגדר באופן מאובטח ב-Render.")
    return secret.encode("utf-8")


def _sign(payload: str) -> str:
    digest = hmac.new(_secret_bytes(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest[:16]


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_member_handoff(member_id: int) -> dict:
    """Create a single-use, short-lived handoff and return its WhatsApp URL."""
    business_number = _digits_only(WHATSAPP_BUSINESS_NUMBER)
    if not business_number:
        raise NovaHandoffError("WHATSAPP_BUSINESS_NUMBER עדיין לא מוגדר ב-Render.")

    nonce = secrets.token_urlsafe(9).rstrip("=")
    token = f"{nonce}.{_sign(nonce)}"
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=max(1, int(NOVA_HANDOFF_TTL_MINUTES)))

    with connection() as conn:
        # Keep the table small and make previous unused handoffs for this member invalid.
        conn.execute(
            "UPDATE whatsapp_handoffs SET used_at=? WHERE member_id=? AND used_at IS NULL",
            (utc_now_iso(), int(member_id)),
        )
        conn.execute(
            """INSERT INTO whatsapp_handoffs(token_hash,member_id,expires_at,used_at,created_at)
               VALUES(?,?,?,?,?)""",
            (_token_hash(token), int(member_id), expires.isoformat(), None, now.isoformat()),
        )
        conn.commit()

    message = f"היי אריאלה 👋 אני רוצה להתחבר לנייד. קוד חיבור: {token}"
    return {
        "token": token,
        "expires_at": expires.isoformat(),
        "url": f"https://wa.me/{business_number}?text={quote(message)}",
    }


def consume_member_handoff(token: str, wa_phone: str) -> int:
    """Verify and consume a handoff, linking the confirmed WhatsApp identity.

    This is intentionally a service helper rather than a public HTTP endpoint.
    Phase N2's verified Meta webhook should call it using the sender phone from
    Meta, never a phone supplied by a browser/client.
    """
    raw = (token or "").strip()
    try:
        nonce, signature = raw.rsplit(".", 1)
    except ValueError as exc:
        raise NovaHandoffError("קוד החיבור אינו תקין.") from exc
    if not nonce or not hmac.compare_digest(signature, _sign(nonce)):
        raise NovaHandoffError("קוד החיבור אינו תקין.")

    phone = _digits_only(wa_phone)
    if not phone:
        raise NovaHandoffError("זהות ה-WhatsApp אינה תקינה.")
    phone_hash = hashlib.sha256(phone.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)

    with connection() as conn:
        row = conn.execute(
            """SELECT id,member_id,expires_at,used_at FROM whatsapp_handoffs
               WHERE token_hash=?""",
            (_token_hash(raw),),
        ).fetchone()
        if not row or row["used_at"]:
            raise NovaHandoffError("קוד החיבור כבר נוצל או אינו קיים.")
        try:
            expires_at = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
        except ValueError as exc:
            raise NovaHandoffError("קוד החיבור אינו תקין.") from exc
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            conn.execute("UPDATE whatsapp_handoffs SET used_at=? WHERE id=?", (now.isoformat(), row["id"]))
            conn.commit()
            raise NovaHandoffError("קוד החיבור פג תוקף. יש ליצור קוד חדש מהאתר.")

        member_id = int(row["member_id"])
        existing_phone = conn.execute(
            "SELECT member_id FROM whatsapp_member_links WHERE wa_phone_hash=? AND status='active'",
            (phone_hash,),
        ).fetchone()
        if existing_phone and int(existing_phone["member_id"]) != member_id:
            raise NovaHandoffError("מספר ה-WhatsApp הזה כבר מקושר לחשבון אחר.")

        timestamp = now.isoformat()
        conn.execute(
            """INSERT INTO whatsapp_member_links(member_id,wa_phone_hash,verified_at,status,created_at,updated_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(member_id) DO UPDATE SET
                 wa_phone_hash=excluded.wa_phone_hash,
                 verified_at=excluded.verified_at,
                 status='active',
                 updated_at=excluded.updated_at""",
            (member_id, phone_hash, timestamp, "active", timestamp, timestamp),
        )
        conn.execute("UPDATE whatsapp_handoffs SET used_at=? WHERE id=?", (timestamp, row["id"]))
        conn.commit()
    return member_id


def member_whatsapp_link_status(member_id: int) -> dict:
    with connection() as conn:
        row = conn.execute(
            "SELECT verified_at,status FROM whatsapp_member_links WHERE member_id=?",
            (int(member_id),),
        ).fetchone()
    if not row:
        return {"linked": False, "status": "not_linked", "verified_at": None}
    return {
        "linked": str(row["status"] or "") == "active",
        "status": row["status"],
        "verified_at": row["verified_at"],
    }
