# MySQL Backup Trigger API

A lightweight FastAPI service that triggers MySQL backups through an authenticated API call and uploads compressed `.sql.gz` dumps to MinIO or S3-compatible storage.

This project does not use cron, shell entrypoints, custom S3 signing scripts, schemas, SQLAlchemy models, or an ORM. Backups run only when `POST /backups/run` is called with the configured API key.

## Features

- API-triggered MySQL backups
- Multi-database support through comma-separated `DB_NAMES`
- Gzip-compressed `mysqldump` output
- MinIO/S3 upload using `boto3`
- API key protection with `X-API-Key`
- Simple health and DB connectivity endpoints
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
BACKUP_TIMEOUT=3600
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

Check database connectivity:

```bash
curl -H "X-API-Key: change-this-long-random-secret" \
  http://localhost:8000/db-check
```

Trigger a backup:

```bash
curl -X POST \
  -H "X-API-Key: change-this-long-random-secret" \
  http://localhost:8000/backups/run
```

## API

### `GET /health`

Public health endpoint.

```json
{"status": "ok"}
```

### `GET /db-check`

Requires:

```text
X-API-Key: <BACKUP_API_KEY>
```

Returns:

```json
{"status": "connected"}
```

### `POST /backups/run`

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
      "s3_key": "backups/database1/database1_2026-06-17_10-30-00.sql.gz"
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
| `BACKUP_TIMEOUT` | no | `3600` | Max seconds per `mysqldump` |

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

- Backups are not scheduled by this service. Call `POST /backups/run` from your app, CI/CD, Coolify task, cron outside the container, or another scheduler.
- Logs go to container stdout/stderr and can be viewed with `docker logs db-backup`.
- Protect this service from public traffic. The backup endpoint can create database dumps and upload them to object storage.
