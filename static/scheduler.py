import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from config import (
    DAILY_SEND_HOUR, DAILY_SEND_MINUTE, ISRAEL_TZ,
    WIDE_SCAN_HOUR, WIDE_SCAN_MINUTE,
)
from daily import prepare_daily_batch
from scanner import run_wide_scan

log = logging.getLogger(__name__)
_scheduler = None


def _safe_public_db_refresh():
    """Hourly DB-only refresh. Never spends SerpAPI requests."""
    try:
        # Lazy import avoids a startup circular import with the Flask blueprint.
        from public_site import refresh_public_deal_feed
        result = refresh_public_deal_feed(limit=30)
        log.info("Hourly public DB refresh complete: %s", result)
    except Exception:
        log.exception("Hourly public DB refresh failed")


def _safe_daily_wide_scan():
    """One system-wide external discovery scan per day."""
    try:
        result = run_wide_scan()
        log.info("Daily wide scan complete: %s", result)
        # Re-rank the shared DB immediately after the external inventory grows.
        _safe_public_db_refresh()
    except Exception:
        log.exception("Daily wide scan failed")


def _safe_daily_batch():
    try:
        result = prepare_daily_batch()
        log.info("Daily batch prepared: status=%s count=%s", result["batch"]["status"], len(result["deals"]))
    except Exception:
        log.exception("Daily batch preparation failed")


def start_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler
    _scheduler = BackgroundScheduler(timezone=ISRAEL_TZ)
    # Every hour: DB-only Top Deals refresh. No external flight search.
    _scheduler.add_job(_safe_public_db_refresh, CronTrigger(minute=5), id="hourly_public_db_refresh", replace_existing=True, max_instances=1, coalesce=True)
    # Once per day: system-wide external inventory discovery (TLV + HFA).
    _scheduler.add_job(_safe_daily_wide_scan, CronTrigger(hour=WIDE_SCAN_HOUR, minute=WIDE_SCAN_MINUTE), id="daily_wide_scan", replace_existing=True, max_instances=1, coalesce=True)
    _scheduler.add_job(_safe_daily_batch, CronTrigger(hour=DAILY_SEND_HOUR, minute=DAILY_SEND_MINUTE), id="daily_batch", replace_existing=True, max_instances=1, coalesce=True)
    _scheduler.start()
    return _scheduler
