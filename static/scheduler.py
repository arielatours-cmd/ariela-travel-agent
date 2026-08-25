import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from config import DAILY_SEND_HOUR, DAILY_SEND_MINUTE, ISRAEL_TZ, MAX_SEARCHES_PER_SCAN
from daily import prepare_daily_batch
from scanner import run_hourly_scan

log = logging.getLogger(__name__)
_scheduler = None


def _safe_scan():
    try:
        result = run_hourly_scan(MAX_SEARCHES_PER_SCAN)
        log.info("Hourly scan complete: %s", result)
    except Exception:
        log.exception("Hourly scan failed")


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
    _scheduler.add_job(_safe_scan, CronTrigger(minute=5), id="hourly_scan", replace_existing=True, max_instances=1, coalesce=True)
    _scheduler.add_job(_safe_daily_batch, CronTrigger(hour=DAILY_SEND_HOUR, minute=DAILY_SEND_MINUTE), id="daily_batch", replace_existing=True, max_instances=1, coalesce=True)
    _scheduler.start()
    return _scheduler
