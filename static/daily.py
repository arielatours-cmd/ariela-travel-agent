from datetime import datetime
from zoneinfo import ZoneInfo
from config import ISRAEL_TZ
from database import save_daily_batch
from formatter import build_daily_message
from schedule_rules import delivery_status
from selector import select_daily_deals


def prepare_daily_batch(force: bool = False) -> dict:
    now = datetime.now(ZoneInfo(ISRAEL_TZ))
    rule = delivery_status(now)
    deals = select_daily_deals()
    message = build_daily_message(deals)
    status = "ready" if (force or rule["allowed"]) and deals else "blocked" if deals else "empty"
    batch = save_daily_batch(now.date().isoformat(), message, deals, status=status)
    return {"batch": batch, "delivery_rule": rule, "deals": deals, "message": message}
