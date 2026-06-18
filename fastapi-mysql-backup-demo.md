# FastAPI MySQL Backup Trigger Implementation

This repository is a FastAPI service that connects to MySQL and exposes an authenticated endpoint to trigger backups. It does not use models, schemas, SQLAlchemy, cron, shell entrypoints, or custom S3 signing scripts.

## Runtime Shape

```text
app/
├── __init__.py
├── backup.py
└── main.py
Dockerfile
docker-compose.yml
requirements.txt
.env.example
```

## Environment Variables

```env
DB_HOST=mysql
DB_PORT=3306
DB_USER=root
DB_PASSWORD=root_password
DB_NAMES=fastapi_app
DB_SSL_MODE=DISABLED

S3_ENDPOINT=http://minio:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin123
S3_BUCKET=fastapi-backups
S3_PATH_PREFIX=backups
S3_REGION=us-east-1

BACKUP_API_KEY=change-this-long-random-secret
BACKUP_TIMEOUT=3600
MAX_BACKUPS_PER_DATABASE=30
```

`DB_NAMES` can contain one database or multiple comma-separated database names.

## API

### Health

```bash
curl http://localhost:8000/health
```

Returns:

```json
{"status": "ok"}
```

### DB Check

```bash
curl -H "X-API-Key: change-this-long-random-secret" \
  http://localhost:8000/db-check
```

Returns:

```json
{"status": "connected"}
```

### Trigger Backup

```bash
curl -X POST \
  -H "X-API-Key: change-this-long-random-secret" \
  http://localhost:8000/backups/run
```

Example response:

```json
{
  "status": "success",
  "timestamp": "2026-06-17_10-30-00",
  "results": [
    {
      "database": "fastapi_app",
      "status": "success",
      "s3_key": "backups/fastapi_app/fastapi_app_2026-06-17_10-30-00.sql.gz",
      "deleted_old_backups": []
    }
  ]
}
```

## Behavior

- `GET /health` is public.
- `GET /db-check` and `POST /backups/run` require `X-API-Key`.
- Only one backup can run at a time; concurrent backup requests return HTTP `409`.
- Each backup runs `mysqldump`, compresses the dump with gzip, and uploads it with `boto3`.
- After each successful upload, older `.sql.gz` backups beyond `MAX_BACKUPS_PER_DATABASE` are deleted for that database.
- Failures for individual databases are returned in the `results` array.
- Missing configuration or S3 setup errors return HTTP `500`.

## Backup Object Path

```text
S3_BUCKET/
└── S3_PATH_PREFIX/
    └── database_name/
        └── database_name_YYYY-MM-DD_HH-MM-SS.sql.gz
```

## Local Run

```bash
cp .env.example .env
docker compose up -d --build
```

Then call:

```bash
curl -X POST \
  -H "X-API-Key: change-this-long-random-secret" \
  http://localhost:8000/backups/run
```
