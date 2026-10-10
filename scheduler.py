import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from config import (
    DAILY_SEND_HOUR, DAILY_SEND_MINUTE, ISRAEL_TZ,
    WIDE_SCAN_HOUR, WIDE_SCAN_MINUTE,
    PERSONAL_SEARCH_DAILY_SCAN_HOUR, PERSONAL_SEARCH_DAILY_SCAN_MINUTE,
    CJ_COMMISSIONS_SYNC_HOUR, CJ_COMMISSIONS_SYNC_MINUTE,
    HOW_WAS_IT_HOUR, HOW_WAS_IT_MINUTE,
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
    try:
        # Free re-match (no SerpAPI spend) for every personal-tracking trip
        # against whatever today's scanning already found - runs every day,
        # including Friday/Saturday, since this never spends external search
        # budget. The delivery-timing rule above only governs when it's
        # acceptable to actually SEND a message, not whether the trip's own
        # saved card may already reflect the best match found so far.
        from public_site import run_personal_vacation_evening_refresh
        refresh_result = run_personal_vacation_evening_refresh()
        log.info("Evening personal vacation refresh complete: %s", refresh_result)
    except Exception:
        log.exception("Evening personal vacation refresh failed")


_PAID_SEARCH_LAST_RUN_KEY = "paid_personal_search_last_run_date"


def _israel_now():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo(ISRAEL_TZ))


def _safe_paid_personal_search():
    """Noon scan for customers on the paid 39 ILS personal-search tier only.

    Never runs on Saturday (business owner's explicit rule: no searches go
    out on Shabbat at all, full stop - not a delivery-timing nuance like the
    general daily batch's Friday/Saturday summer-winter rule, which governs
    when a message may be SENT, not whether this dedicated search may spend
    SerpAPI budget that day). The evening personal-vacation refresh (see
    _safe_daily_batch) still runs every day including Saturday, since it
    only re-matches already-gathered data and spends nothing."""
    try:
        if _israel_now().weekday() == 5:
            log.info("Paid personal search batch skipped - Saturday")
            return
        # Lazy import avoids a startup circular import with the Flask blueprint.
        from public_site import run_paid_personal_search_batch
        from database import get_setting, set_setting
        # The catch-up job may already have run today's batch (e.g. after a
        # restart); never spend SerpAPI on a second batch the same day.
        if get_setting(_PAID_SEARCH_LAST_RUN_KEY) == _israel_now().date().isoformat():
            log.info("Paid personal search batch already ran today - skipping")
            return
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
        if now.weekday() == 5:
            return
        due = (now.hour, now.minute) >= (PERSONAL_SEARCH_DAILY_SCAN_HOUR, PERSONAL_SEARCH_DAILY_SCAN_MINUTE)
        if due and get_setting(_PAID_SEARCH_LAST_RUN_KEY) != now.date().isoformat():
            log.warning("Paid personal search batch missed today - running catch-up now")
            _safe_paid_personal_search()
    except Exception:
        log.exception("Paid personal search catch-up check failed")


def _safe_cj_commissions_sync():
    try:
        from partner_commissions import sync_cj_commissions
        result = sync_cj_commissions()
        log.info("CJ commission sync complete: %s", result)
    except Exception:
        log.exception("CJ commission sync failed")


def _safe_how_was_it_queue():
    try:
        from trip_lifecycle_messages import queue_how_was_it_messages
        result = queue_how_was_it_messages()
        log.info("How-was-it queue complete: %s", result)
    except Exception:
        log.exception("How-was-it queue failed")


def start_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler
    # APScheduler's default misfire grace is 1 second: a job that wakes even
    # slightly late is dropped for the whole day. Allow an hour instead.
    # Every CronTrigger below passes timezone=ISRAEL_TZ explicitly: a bare
    # CronTrigger(...) object ignores the scheduler's timezone and uses the
    # server's local zone (UTC on Render), which silently moved the noon paid
    # scan to 15:00 and the 17:00 batch to 20:00 Israel time.
    _scheduler = BackgroundScheduler(timezone=ISRAEL_TZ, job_defaults={"misfire_grace_time": 3600, "coalesce": True})
    # Every hour: DB-only Top Deals refresh. No external flight search.
    _scheduler.add_job(_safe_public_db_refresh, CronTrigger(minute=5, timezone=ISRAEL_TZ), id="hourly_public_db_refresh", replace_existing=True, max_instances=1, coalesce=True)
    # Once per day: system-wide external inventory discovery (TLV + HFA).
    # PAUSED at the business owner's request - this is the SerpAPI-spending job
    # and there is no budget for it until launch. Re-enable this line (and
    # redeploy) when ready to resume automatic daily scanning.
    # _scheduler.add_job(_safe_daily_wide_scan, CronTrigger(hour=WIDE_SCAN_HOUR, minute=WIDE_SCAN_MINUTE, timezone=ISRAEL_TZ), id="daily_wide_scan", replace_existing=True, max_instances=1, coalesce=True)
    _scheduler.add_job(_safe_daily_batch, CronTrigger(hour=DAILY_SEND_HOUR, minute=DAILY_SEND_MINUTE, timezone=ISRAEL_TZ), id="daily_batch", replace_existing=True, max_instances=1, coalesce=True)
    # Once per day: dedicated search for customers on the paid 39 ILS personal-search tier.
    _scheduler.add_job(_safe_paid_personal_search, CronTrigger(hour=PERSONAL_SEARCH_DAILY_SCAN_HOUR, minute=PERSONAL_SEARCH_DAILY_SCAN_MINUTE, timezone=ISRAEL_TZ), id="paid_personal_search", replace_existing=True, max_instances=1, coalesce=True)
    # Safety net for a missed noon run (restart/deploy/late wake-up): hourly,
    # plus once shortly after startup.
    _scheduler.add_job(_paid_personal_search_catch_up, CronTrigger(minute=35, timezone=ISRAEL_TZ), id="paid_personal_search_catch_up", replace_existing=True, max_instances=1, coalesce=True)
    from datetime import timedelta
    _scheduler.add_job(_paid_personal_search_catch_up, "date", run_date=_israel_now() + timedelta(minutes=2), id="paid_personal_search_startup_catch_up", replace_existing=True)
    # Once per day: CJ commission sync (booking-credit detection, task 001a).
    # No-ops internally when CJ_COMMISSIONS_SYNC_ENABLED is false/unset.
    _scheduler.add_job(_safe_cj_commissions_sync, CronTrigger(hour=CJ_COMMISSIONS_SYNC_HOUR, minute=CJ_COMMISSIONS_SYNC_MINUTE, timezone=ISRAEL_TZ), id="cj_commissions_sync", replace_existing=True, max_instances=1, coalesce=True)
    # Once per day: queue "איך היה?" for trips that returned 2+ days ago.
    _scheduler.add_job(_safe_how_was_it_queue, CronTrigger(hour=HOW_WAS_IT_HOUR, minute=HOW_WAS_IT_MINUTE, timezone=ISRAEL_TZ), id="how_was_it_queue", replace_existing=True, max_instances=1, coalesce=True)
    _scheduler.start()
    return _scheduler
