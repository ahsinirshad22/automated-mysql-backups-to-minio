import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.backup import BackupAlreadyRunning, create_backups, required_env
from app.notifications import backup_result_failed, notify_backup_failure


logger = logging.getLogger(__name__)
scheduler: BackgroundScheduler | None = None


def run_scheduled_backup() -> None:
    logger.info("Scheduled backup started")
    try:
        result = create_backups()
    except BackupAlreadyRunning:
        logger.warning("Scheduled backup skipped because another backup is running")
        return
    except Exception as exc:
        logger.exception("Scheduled backup crashed")
        notify_backup_failure("scheduled", {"error": str(exc)})
        return

    if backup_result_failed(result):
        notify_backup_failure("scheduled", result)

    logger.info("Scheduled backup finished with status %s", result.get("status"))


def start_scheduler() -> None:
    global scheduler

    if scheduler and scheduler.running:
        return

    schedule = required_env("BACKUP_CRON_SCHEDULE")
    timezone = required_env("BACKUP_CRON_TIMEZONE")
    trigger = CronTrigger.from_crontab(schedule, timezone=timezone)

    scheduler = BackgroundScheduler(timezone=timezone)
    scheduler.add_job(
        run_scheduled_backup,
        trigger,
        id="automated_mysql_backup",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.start()
    logger.info("Backup scheduler started with schedule %s in %s", schedule, timezone)


def stop_scheduler() -> None:
    global scheduler

    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Backup scheduler stopped")
    scheduler = None
