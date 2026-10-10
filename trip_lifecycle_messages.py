"""Booking-lifecycle WhatsApp messages (task 001a): "תיהנו בטיול" right
after a booking is detected, and "איך היה?" a couple of days after the trip
returns. Everything is queued in whatsapp_outbound_queue as 'preview' -
nothing is ever sent from here.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from config import ISRAEL_TZ
from database import connection, utc_now_iso, queue_whatsapp_message

log = logging.getLogger(__name__)

HOW_WAS_IT_MIN_DAYS_AFTER_RETURN = 2
HOW_WAS_IT_MAX_DAYS_AFTER_RETURN = 30

_RATING_LABELS = {3: "😍 מעולה", 2: "🙂 היה בסדר", 1: "😕 פחות"}


def _trip_destination_name(answers: dict, request_name: str) -> str:
    return str(answers.get("destination_display") or request_name or "היעד שלכם")


def _parse_date(value):
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except Exception:
        return None


def queue_booking_congrats(trip_id: int) -> int | None:
    """Queues the one-time "תיהנו בטיול" message. No-op if already queued
    for this trip (congrats_queued_at already set)."""
    with connection() as conn:
        row = conn.execute(
            "SELECT member_id, request_name, answers_json, congrats_queued_at FROM trip_requests WHERE id=?",
            (trip_id,),
        ).fetchone()
        if not row or row["congrats_queued_at"]:
            return None
        member_id = int(row["member_id"])
        try:
            answers = json.loads(row["answers_json"] or "{}")
        except Exception:
            answers = {}
        destination = _trip_destination_name(answers, row["request_name"])

        lines = ["🎉 *איזה כיף — ההזמנה נקלטה!*"]
        departure = _parse_date(answers.get("departure_date"))
        today_israel = datetime.now(ZoneInfo(ISRAEL_TZ)).date()
        if departure and departure >= today_israel:
            days_until = (departure - today_israel).days
            when = f"בעוד {days_until} ימים" if days_until != 1 else "מחר"
            if days_until == 0:
                when = "היום"
            lines.append(f"{destination} מחכה לכם {when}.")
        lines.append("אם תצטרכו משהו לפני הטיסה - פשוט כתבו לאריאלה כאן 🌷")
        lines.append("שתהיה לכם חופשה מושלמת! ✈️")
        message_text = "\n".join(lines)

        queue_id = queue_whatsapp_message(
            member_id, "booking_congrats", message_text,
            buttons=[{"text": "החופשות שלי", "url": "/account"}], ref_id=trip_id,
        )
        conn.execute(
            "UPDATE trip_requests SET congrats_queued_at=? WHERE id=?",
            (utc_now_iso(), trip_id),
        )
        conn.commit()
    return queue_id


def queue_how_was_it_messages() -> dict:
    """Daily job: every booked, not-cancelled trip whose return date was at
    least HOW_WAS_IT_MIN_DAYS_AFTER_RETURN days ago (Israel time) and no
    more than HOW_WAS_IT_MAX_DAYS_AFTER_RETURN days ago, not yet queued,
    gets the "איך היה?" message with its 3 rating buttons."""
    today_israel = datetime.now(ZoneInfo(ISRAEL_TZ)).date()
    queued = []
    with connection() as conn:
        rows = conn.execute(
            "SELECT id, member_id, request_name, answers_json FROM trip_requests "
            "WHERE booked_confirmed_at IS NOT NULL AND booking_cancelled_at IS NULL "
            "AND how_was_it_queued_at IS NULL"
        ).fetchall()
    for row in rows:
        try:
            answers = json.loads(row["answers_json"] or "{}")
        except Exception:
            answers = {}
        return_date = _parse_date(answers.get("return_date"))
        if not return_date:
            continue
        days_since_return = (today_israel - return_date).days
        if days_since_return < HOW_WAS_IT_MIN_DAYS_AFTER_RETURN or days_since_return > HOW_WAS_IT_MAX_DAYS_AFTER_RETURN:
            continue
        trip_id = int(row["id"])
        destination = _trip_destination_name(answers, row["request_name"])
        message_text = f"👋 *ברוכים השבים!*\nאיך היה ב{destination}?"
        buttons = [
            {"text": label, "payload": f"HOW_WAS_IT:{trip_id}:{rating}"}
            for rating, label in sorted(_RATING_LABELS.items(), reverse=True)
        ]
        with connection() as conn:
            queue_whatsapp_message(int(row["member_id"]), "how_was_it", message_text, buttons=buttons, ref_id=trip_id)
            conn.execute(
                "UPDATE trip_requests SET how_was_it_queued_at=? WHERE id=?",
                (utc_now_iso(), trip_id),
            )
            conn.commit()
        queued.append(trip_id)
    return {"checked": len(rows), "queued": queued}
