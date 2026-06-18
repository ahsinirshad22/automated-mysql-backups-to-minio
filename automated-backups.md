# Automated Backup API Plan

This project now uses an API-triggered backup model instead of an internal cron daemon.

## Current Design

- FastAPI serves the backup API on port `8000`.
- `GET /health` is public.
- `GET /db-check` verifies the MySQL connection and requires `X-API-Key`.
- `POST /backups/run` triggers backups and requires `X-API-Key`.
- `mysqldump` creates one dump per database in `DB_NAMES`.
- Dumps are compressed as `.sql.gz`.
- Uploads use `boto3` against MinIO or any S3-compatible endpoint.

## Removed Old Logic

- No cron daemon.
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
BACKUP_TIMEOUT=3600
MAX_BACKUPS_PER_DATABASE=30
```

## Retention

After a database backup uploads successfully, the API lists `.sql.gz` objects under that database prefix, keeps the latest `MAX_BACKUPS_PER_DATABASE`, and deletes older objects.

Set `MAX_BACKUPS_PER_DATABASE=0` to disable cleanup.
