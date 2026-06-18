# MySQL Backup Trigger API

A lightweight FastAPI service that triggers MySQL backups through an authenticated API call and uploads compressed `.sql.gz` dumps to MinIO or S3-compatible storage.

This project uses FastAPI for instant backup triggers and an in-app cron scheduler for automated backups. It does not use OS cron, shell entrypoints, custom S3 signing scripts, schemas, SQLAlchemy models, or an ORM.

## Features

- API-triggered MySQL backups
- Automated in-app cron backups
- Multi-database support through comma-separated `DB_NAMES`
- Gzip-compressed `mysqldump` output
- MinIO/S3 upload using `boto3`
- API key protection with `X-API-Key`
- Simple health and DB connectivity endpoints
- Failure emails through SMTP
- Optional MySQL TLS modes for self-signed or CA-verified connections

## Quick Start

```bash
cp .env.example .env
```

Edit `.env`:

```env
DB_HOST=mysql-server
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_password
DB_NAMES=database1,database2
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

Build and run:

```bash
docker compose up -d --build
```

## Run Locally

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The app loads `.env` automatically when running locally, so you do not need to run `source .env`.

Run the API locally:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Or run it without activating the environment:

```bash
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Check health:

```bash
curl http://localhost:8000/health
```

Check service status:

```bash
curl http://localhost:8000/
```

Open the same URL in a browser for the HTML status dashboard.

Check database connectivity:

```bash
curl http://localhost:8000/status/database
```

Check S3, SMTP, and cron status:

```bash
curl http://localhost:8000/status/s3
curl http://localhost:8000/status/smtp
curl http://localhost:8000/status/cron
```

Trigger a backup:

```bash
curl -X POST \
  -H "X-API-Key: change-this-long-random-secret" \
  http://localhost:8000/backup/generate
```

## API

### `GET /`

Public HTML service status dashboard.

Shows database, S3 API, SMTP, and cron scheduler status. The same endpoint can be opened in a browser.

Invalid SMTP or S3 settings fail safely and render as `Not Connected` cards instead of crashing the page.

### `GET /health`

Public health endpoint.

```json
{"status": "ok"}
```

### `GET /status/database`

Public database status endpoint.

```json
{
  "status": "connected",
  "message": "Database connection success"
}
```

### `GET /status/s3`

Public S3 API status endpoint.

```json
{
  "status": "connected",
  "message": "S3 API connection success"
}
```

### `GET /status/smtp`

Public SMTP status endpoint.

```json
{
  "status": "connected",
  "message": "SMTP connection success"
}
```

### `GET /status/cron`

Public cron scheduler status endpoint.

```json
{
  "status": "running",
  "schedule": "0 2 * * *",
  "timezone": "Asia/Karachi",
  "next_run_time": "2026-06-19T02:00:00+05:00",
  "message": "Cron scheduler is running"
}
```

### `POST /backup/generate`

Requires:

```text
X-API-Key: <BACKUP_API_KEY>
```

Runs a backup for every database in `DB_NAMES`.

Example response:

```json
{
  "status": "success",
  "timestamp": "2026-06-17_10-30-00",
  "results": [
    {
      "database": "database1",
      "status": "success",
      "s3_key": "backups/database1/database1_2026-06-17_10-30-00.sql.gz",
      "deleted_old_backups": []
    }
  ]
}
```

If a backup is already running, the endpoint returns HTTP `409`.

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DB_HOST` | yes | - | MySQL host |
| `DB_PORT` | no | `3306` | MySQL port |
| `DB_USER` | yes | - | MySQL user |
| `DB_PASSWORD` | yes | - | MySQL password |
| `DB_NAMES` | yes | - | Comma-separated database names |
| `DB_SSL_MODE` | no | `DISABLED` | `DISABLED`, `PREFERRED`, `VERIFY_DISABLED`, or `VERIFY_CA` |
| `DB_SSL_CA` | if `VERIFY_CA` | - | CA file path for MySQL TLS verification |
| `S3_ENDPOINT` | yes | - | MinIO/S3 endpoint URL |
| `S3_ACCESS_KEY` | yes | - | S3 access key |
| `S3_SECRET_KEY` | yes | - | S3 secret key |
| `S3_BUCKET` | yes | - | Target bucket |
| `S3_PATH_PREFIX` | no | `backups` | Object key prefix |
| `S3_REGION` | no | `us-east-1` | S3 region |
| `BACKUP_API_KEY` | yes | - | API key required for protected endpoints |
| `BACKUP_CRON_SCHEDULE` | no | - | Cron expression for automated backups; blank disables scheduling |
| `BACKUP_CRON_TIMEZONE` | if scheduling | - | Timezone for automated backups, e.g. `Asia/Karachi` |
| `BACKUP_TIMEOUT` | no | `3600` | Max seconds per `mysqldump` |
| `MAX_BACKUPS_PER_DATABASE` | no | `30` | Keep only the latest N `.sql.gz` backups per database; `0` disables cleanup |
| `SMTP_HOST` | on failure email | - | SMTP server host |
| `SMTP_PORT` | on failure email | - | SMTP server port |
| `SMTP_USERNAME` | no | - | SMTP username |
| `SMTP_PASSWORD` | no | - | SMTP password |
| `SMTP_FROM_EMAIL` | on failure email | - | Sender email address |
| `SMTP_TO_EMAIL` | on failure email | - | Recipient email address |
| `SMTP_SECURITY` | no | `STARTTLS` | `STARTTLS`, `SSL`, or `NONE` |
| `HOST_EMAIL` | no | - | Host/admin email included in failure email body |

## Automated Backups

Automated backups run inside the FastAPI process using `BACKUP_CRON_SCHEDULE` and `BACKUP_CRON_TIMEZONE`.

```env
BACKUP_CRON_SCHEDULE=0 2 * * *
BACKUP_CRON_TIMEZONE=Asia/Karachi
```

Manual backups still work through `POST /backup/generate`.

Leave `BACKUP_CRON_SCHEDULE` blank to disable automated backups without stopping the app.

## Failure Emails

Failure emails are sent when a manual or scheduled backup fails for any database, or when the backup job crashes before returning a normal result.

Set SMTP encryption with one variable:

```env
SMTP_SECURITY=STARTTLS
```

Allowed values are `STARTTLS`, `SSL`, and `NONE`.

## Backup Layout

```text
S3_BUCKET/
└── S3_PATH_PREFIX/
    └── database_name/
        └── database_name_YYYY-MM-DD_HH-MM-SS.sql.gz
```

## Restore

Download the `.sql.gz` object from MinIO/S3, then restore:

```bash
gunzip < database_name_YYYY-MM-DD_HH-MM-SS.sql.gz | mysql \
  -h mysql-host \
  -P 3306 \
  -u root \
  -p database_name
```

## Notes

- Backups can be triggered instantly through `POST /backup/generate` and automatically through the in-app cron scheduler.
- After each successful database upload, the service deletes older `.sql.gz` objects beyond `MAX_BACKUPS_PER_DATABASE` for that database prefix.
- Logs go to container stdout/stderr and can be viewed with `docker logs db-backup`.
- Protect this service from public traffic. The backup endpoint can create database dumps and upload them to object storage.
