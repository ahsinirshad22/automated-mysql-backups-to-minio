# Automated Backup API Plan

This project uses FastAPI for instant backups and an in-app cron scheduler for automated backups. It does not use an OS cron daemon.

## Current Design

- FastAPI serves the backup API on port `8000`.
- `GET /health` is public.
- `GET /db-check` verifies the MySQL connection and requires `X-API-Key`.
- `POST /backups/run` triggers instant backups and requires `X-API-Key`.
- Automated backups run from `BACKUP_CRON_SCHEDULE` in `BACKUP_CRON_TIMEZONE`.
- `mysqldump` creates one dump per database in `DB_NAMES`.
- Dumps are compressed as `.sql.gz`.
- Uploads use `boto3` against MinIO or any S3-compatible endpoint.

## Removed Old Logic

- No OS cron daemon.
- No startup backup.
- No shell `entrypoint.sh`.
- No shell `backup.sh`.
- No custom shell AWS Signature V4 code.
- No retention cleanup inside this container.
- No `/var/log/backup.log`; logs go to stdout/stderr.

## Required Environment

```env
DB_HOST=mysql
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_mysql_password
DB_NAMES=db1,db2
DB_SSL_MODE=DISABLED

S3_ENDPOINT=http://minio:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=strongpassword
S3_BUCKET=db-backups
S3_PATH_PREFIX=backups
S3_REGION=us-east-1

BACKUP_API_KEY=change-this-long-random-secret
BACKUP_CRON_SCHEDULE=0 2 * * *
BACKUP_CRON_TIMEZONE=Asia/Karachi
BACKUP_TIMEOUT=3600
MAX_BACKUPS_PER_DATABASE=30

SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=user@example.com
SMTP_PASSWORD=your_smtp_password
SMTP_FROM_EMAIL=backups@example.com
SMTP_TO_EMAIL=admin@example.com
SMTP_SECURITY=STARTTLS
HOST_EMAIL=host@example.com
```

## Failure Emails

Failure emails are sent for manual and scheduled backups when any database backup fails or the job crashes.

`SMTP_SECURITY` accepts `STARTTLS`, `SSL`, or `NONE`.

## Retention

After a database backup uploads successfully, the API lists `.sql.gz` objects under that database prefix, keeps the latest `MAX_BACKUPS_PER_DATABASE`, and deletes older objects.

Set `MAX_BACKUPS_PER_DATABASE=0` to disable cleanup.
