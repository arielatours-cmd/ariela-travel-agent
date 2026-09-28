import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from config import (
    DAILY_SEND_HOUR, DAILY_SEND_MINUTE, ISRAEL_TZ,
    WIDE_SCAN_HOUR, WIDE_SCAN_MINUTE,
    PERSONAL_SEARCH_DAILY_SCAN_HOUR, PERSONAL_SEARCH_DAILY_SCAN_MINUTE,
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


_PAID_SEARCH_LAST_RUN_KEY = "paid_personal_search_last_run_date"


def _israel_now():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo(ISRAEL_TZ))


def _safe_paid_personal_search():
    """Noon scan for customers on the paid 39 ILS personal-search tier only."""
    try:
        # Lazy import avoids a startup circular import with the Flask blueprint.
        from public_site import run_paid_personal_search_batch
        from database import set_setting
        # Mark the day first so a catch-up check running at the same time
        # never starts a second, duplicate (SerpAPI-spending) batch.
        set_setting(_PAID_SEARCH_LAST_RUN_KEY, _israel_now().date().isoformat())
        result = run_paid_personal_search_batch()
        log.info("Paid personal search batch complete: %s", result)
    except Exception:
        log.exception("Paid personal search batch failed")


def _paid_personal_search_catch_up():
    """Seen live: a paying customer's noon scan simply never happened, with
    nothing recorded anywhere. The noon job lives only in this process's
    memory and APScheduler's default misfire grace is ONE second - a restart
    or deploy around noon, or the job waking a moment late, silently drops
    that whole day's paid scan and nothing ever runs it later. This hourly
    check (and one at startup) runs the day's batch if noon has passed and
    it hasn't run yet today."""
    try:
        from database import get_setting
        now = _israel_now()
        due = (now.hour, now.minute) >= (PERSONAL_SEARCH_DAILY_SCAN_HOUR, PERSONAL_SEARCH_DAILY_SCAN_MINUTE)
        if due and get_setting(_PAID_SEARCH_LAST_RUN_KEY) != now.date().isoformat():
            log.warning("Paid personal search batch missed today - running catch-up now")
            _safe_paid_personal_search()
    except Exception:
        log.exception("Paid personal search catch-up check failed")


def start_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler
    # APScheduler's default misfire grace is 1 second: a job that wakes even
    # slightly late is dropped for the whole day. Allow an hour instead.
    _scheduler = BackgroundScheduler(timezone=ISRAEL_TZ, job_defaults={"misfire_grace_time": 3600, "coalesce": True})
    # Every hour: DB-only Top Deals refresh. No external flight search.
    _scheduler.add_job(_safe_public_db_refresh, CronTrigger(minute=5), id="hourly_public_db_refresh", replace_existing=True, max_instances=1, coalesce=True)
    # Once per day: system-wide external inventory discovery (TLV + HFA).
    # PAUSED at the business owner's request - this is the SerpAPI-spending job
    # and there is no budget for it until launch. Re-enable this line (and
    # redeploy) when ready to resume automatic daily scanning.
    # _scheduler.add_job(_safe_daily_wide_scan, CronTrigger(hour=WIDE_SCAN_HOUR, minute=WIDE_SCAN_MINUTE), id="daily_wide_scan", replace_existing=True, max_instances=1, coalesce=True)
    _scheduler.add_job(_safe_daily_batch, CronTrigger(hour=DAILY_SEND_HOUR, minute=DAILY_SEND_MINUTE), id="daily_batch", replace_existing=True, max_instances=1, coalesce=True)
    # Once per day: dedicated search for customers on the paid 39 ILS personal-search tier.
    _scheduler.add_job(_safe_paid_personal_search, CronTrigger(hour=PERSONAL_SEARCH_DAILY_SCAN_HOUR, minute=PERSONAL_SEARCH_DAILY_SCAN_MINUTE), id="paid_personal_search", replace_existing=True, max_instances=1, coalesce=True)
    # Safety net for a missed noon run (restart/deploy/late wake-up): hourly,
    # plus once shortly after startup.
    _scheduler.add_job(_paid_personal_search_catch_up, CronTrigger(minute=35), id="paid_personal_search_catch_up", replace_existing=True, max_instances=1, coalesce=True)
    from datetime import timedelta
    _scheduler.add_job(_paid_personal_search_catch_up, "date", run_date=_israel_now() + timedelta(minutes=2), id="paid_personal_search_startup_catch_up", replace_existing=True)
    _scheduler.start()
    return _scheduler
