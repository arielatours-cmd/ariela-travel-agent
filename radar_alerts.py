"""The personal radar, stage 1 (task 002a): decide whether a tracked trip's
matched flight price is worth telling the customer about, write the
decision + message to trip_alerts_log, and queue it for preview - never
send anything. Wired into the existing paid-search batch jobs
(public_site.run_paid_personal_search_batch / run_personal_vacation_evening_
refresh), always inside a try/except there so a radar failure never breaks
the scan that feeds it.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from config import ISRAEL_TZ
from database import connection, utc_now_iso, recent_offers, queue_whatsapp_message

log = logging.getLogger(__name__)

PRICE_DROP_MIN_PERCENT = 0.05
PRICE_DROP_MIN_ILS = 50.0
LOWEST_SEEN_WINDOW_DAYS = 30

_REASON_LINES = {
    "lowest_seen": "זה המחיר הכי נמוך שראינו לתאריכים האלה בחודש האחרון.",
}


def _israel_date(iso_text: str):
    try:
        dt = datetime.fromisoformat(str(iso_text).replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo(ISRAEL_TZ)).date()


def _cheapest_offer(offer_ids):
    offers = recent_offers(limit=len(offer_ids) or 5, offer_ids=offer_ids)
    if not offers:
        return None
    return min(offers, key=lambda o: float(o.get("price_ils") or 10**12))


def _lowest_seen_last_30_days(route, outbound_date, return_date):
    if not (route and outbound_date and return_date):
        return None
    since = (datetime.now(timezone.utc) - timedelta(days=LOWEST_SEEN_WINDOW_DAYS)).isoformat()
    with connection() as conn:
        row = conn.execute(
            "SELECT MIN(price_ils) AS lowest FROM offers "
            "WHERE route=? AND outbound_date=? AND return_date=? AND observed_at >= ?",
            (route, outbound_date, return_date, since),
        ).fetchone()
    return float(row["lowest"]) if row and row["lowest"] is not None else None


def _build_message(destination_name, price, previous_price, reason, baggage_included, now_israel):
    lines = [f"🎯 *עדכון על החופשה ל{destination_name}*"]
    price_line = f"המחיר ירד ל-{price:.0f} ₪ לאדם"
    if baggage_included:
        price_line += " כולל מזוודה"
    price_line += f"  (היה {previous_price:.0f} ₪)"
    lines.append(price_line)
    if reason == "price_drop":
        lines.append(f"ירידה של {previous_price - price:.0f} ₪ מהעדכון הקודם.")
    else:
        lines.append(_REASON_LINES["lowest_seen"])
    lines.append(f"נבדק היום ב-{now_israel.strftime('%H:%M')}")
    return "\n".join(lines)


def evaluate_trip_alert(trip_id: int) -> dict | None:
    with connection() as conn:
        trip_row = conn.execute("SELECT * FROM trip_requests WHERE id=?", (trip_id,)).fetchone()
    if not trip_row:
        return None
    trip = dict(trip_row)
    if trip.get("subscription_status") != "active" or trip.get("subscription_plan") not in ("scan", "update"):
        return None
    try:
        answers = json.loads(trip.get("answers_json") or "{}")
    except Exception:
        answers = {}
    offer_ids = answers.get("_matched_offer_ids") or []
    if not offer_ids:
        return None
    cheapest = _cheapest_offer(offer_ids)
    if not cheapest:
        return None
    price = cheapest.get("price_ils")
    if not isinstance(price, (int, float)) or price <= 0:
        return None
    price = float(price)

    member_id = int(trip["member_id"])
    now_utc = datetime.now(timezone.utc)
    now_israel = now_utc.astimezone(ZoneInfo(ISRAEL_TZ))

    baseline = trip.get("alert_baseline_price_ils")
    if baseline is None:
        with connection() as conn:
            conn.execute(
                "UPDATE trip_requests SET alert_baseline_price_ils=? WHERE id=?",
                (price, trip_id),
            )
            conn.commit()
        return None

    comparison_price = trip.get("alert_last_price_ils")
    if comparison_price is None:
        comparison_price = baseline
    comparison_price = float(comparison_price)

    last_alert_date = _israel_date(trip.get("alert_last_at")) if trip.get("alert_last_at") else None
    already_alerted_today = last_alert_date == now_israel.date()
    if already_alerted_today:
        return None

    reason = None
    drop_amount = comparison_price - price
    if drop_amount >= PRICE_DROP_MIN_ILS and drop_amount / comparison_price >= PRICE_DROP_MIN_PERCENT:
        reason = "price_drop"
    else:
        lowest_30d = _lowest_seen_last_30_days(
            cheapest.get("route"), cheapest.get("outbound_date"), cheapest.get("return_date")
        )
        if lowest_30d is not None and price <= lowest_30d and price < comparison_price:
            reason = "lowest_seen"

    mobile_notifications = bool(trip.get("mobile_notifications"))
    if not reason:
        return None

    destination_name = cheapest.get("destination_name") or trip.get("request_name") or "היעד שלכם"
    baggage_included = bool(((cheapest.get("baggage") or {}).get("checked_bag_23kg") or {}).get("included"))
    message_text = _build_message(destination_name, price, comparison_price, reason, baggage_included, now_israel)

    with connection() as conn:
        conn.execute(
            """INSERT INTO trip_alerts_log
               (trip_id, member_id, created_at, reason, price_ils, previous_price_ils, offer_id, message_text, status)
               VALUES (?,?,?,?,?,?,?,?, 'preview')""",
            (trip_id, member_id, utc_now_iso(), reason, price, comparison_price, cheapest.get("offer_id"), message_text),
        )
        conn.execute(
            "UPDATE trip_requests SET alert_last_price_ils=?, alert_last_at=? WHERE id=?",
            (price, utc_now_iso(), trip_id),
        )
        conn.commit()

    if mobile_notifications:
        buttons = [
            {"text": "לכל החופשה באתר", "url": f"/account#vacation-{trip_id}"},
            {"text": "החופשות שלי", "url": "/account"},
        ]
        queue_whatsapp_message(
            member_id, "radar", message_text, buttons=buttons,
            image_url=cheapest.get("destination_image_url"), ref_id=trip_id,
        )

    return {
        "trip_id": trip_id, "reason": reason, "price_ils": price,
        "previous_price_ils": comparison_price, "message_text": message_text,
    }
