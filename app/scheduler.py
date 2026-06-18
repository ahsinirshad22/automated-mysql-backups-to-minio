import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.backup import BackupAlreadyRunning, create_backups
from app.notifications import backup_result_failed, notify_backup_failure


logger = logging.getLogger(__name__)
scheduler: BackgroundScheduler | None = None
scheduler_error: str | None = None


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
    global scheduler, scheduler_error

    if scheduler and scheduler.running:
        return

    schedule = os.getenv("BACKUP_CRON_SCHEDULE", "").strip()
    timezone = os.getenv("BACKUP_CRON_TIMEZONE", "").strip()

    if not schedule:
        scheduler_error = "BACKUP_CRON_SCHEDULE is not configured; automated backups are disabled"
        logger.warning(scheduler_error)
        return

    if not timezone:
        scheduler_error = "BACKUP_CRON_TIMEZONE is not configured; automated backups are disabled"
        logger.warning(scheduler_error)
        return

    try:
        trigger = CronTrigger.from_crontab(schedule, timezone=timezone)
    except Exception as exc:
        scheduler_error = f"Invalid cron scheduler configuration: {exc}"
        logger.exception(scheduler_error)
        return

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
    scheduler_error = None
    logger.info("Backup scheduler started with schedule %s in %s", schedule, timezone)


def stop_scheduler() -> None:
    global scheduler, scheduler_error

    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Backup scheduler stopped")
    scheduler = None
    scheduler_error = None


def scheduler_status() -> dict[str, str | None]:
    if not scheduler:
        return {
            "status": "disabled" if scheduler_error else "not_running",
            "schedule": os.getenv("BACKUP_CRON_SCHEDULE"),
            "timezone": os.getenv("BACKUP_CRON_TIMEZONE"),
            "next_run_time": None,
            "message": scheduler_error or "Cron scheduler is not running",
        }

    job = scheduler.get_job("automated_mysql_backup")
    return {
        "status": "running" if scheduler.running else "not_running",
        "schedule": os.getenv("BACKUP_CRON_SCHEDULE"),
        "timezone": os.getenv("BACKUP_CRON_TIMEZONE"),
        "next_run_time": job.next_run_time.isoformat() if job and job.next_run_time else None,
        "message": "Cron scheduler is running" if scheduler.running else "Cron scheduler is not running",
    }
