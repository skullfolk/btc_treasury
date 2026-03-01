"""
APScheduler-based daily refresh scheduler.
Fires once on startup (to ensure fresh data) and then every weekday at 21:05 UTC
(= 4:05 PM US Eastern, 5 minutes after market close).
"""

import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _run_refresh():
    """Import here to avoid circular imports at module level."""
    from backend.refresh import do_refresh
    try:
        logger.info("Scheduled refresh triggered at %s UTC", datetime.utcnow())
        result = do_refresh()
        logger.info(
            "Refresh complete: MSTR=$%.2f  Implied=$%.2f  Signal=%s",
            result["current_price"],
            result["implied_price"],
            result["signal"],
        )
    except Exception as exc:
        logger.error("Refresh failed: %s", exc, exc_info=True)


def start_scheduler():
    global _scheduler
    _scheduler = BackgroundScheduler(timezone="UTC")

    # Daily trigger: weekdays at 21:05 UTC (4:05 PM ET)
    _scheduler.add_job(
        _run_refresh,
        trigger=CronTrigger(day_of_week="mon-fri", hour=21, minute=5, timezone="UTC"),
        id="daily_refresh",
        name="Daily BTC Treasury Refresh",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,  # allow up to 1h late if container was down
    )

    _scheduler.start()
    logger.info("Scheduler started. Daily refresh at 21:05 UTC on weekdays.")
    return _scheduler


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped.")
