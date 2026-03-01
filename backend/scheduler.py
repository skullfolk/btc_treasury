"""
APScheduler-based daily refresh — fires every weekday at 21:05 UTC
(= 4:05 PM US Eastern, 5 min after market close) for ALL supported companies.
"""

import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None


def _run_refresh_all():
    """Refresh all companies. Import here to avoid circular imports."""
    from backend.refresh import do_refresh_all
    logger.info("Scheduled refresh triggered at %s UTC", datetime.utcnow())
    results = do_refresh_all()
    for company, result in results.items():
        logger.info(
            "[%s] price=$%.2f  implied=$%.2f  signal=%s",
            company, result["current_price"], result["implied_price"], result["signal"]
        )


def start_scheduler():
    global _scheduler
    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        _run_refresh_all,
        trigger=CronTrigger(day_of_week="mon-fri", hour=21, minute=5, timezone="UTC"),
        id="daily_refresh_all",
        name="Daily BTC Treasury Refresh (all companies)",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    _scheduler.start()
    logger.info("Scheduler started — daily refresh at 21:05 UTC on weekdays.")
    return _scheduler


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped.")
