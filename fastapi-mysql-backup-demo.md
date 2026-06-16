# FastAPI MySQL Backup Trigger

This guide creates a minimal FastAPI project that connects to MySQL and exposes an API endpoint to trigger database backups.

There are no SQLAlchemy models, no Pydantic schemas, and no application tables required. The FastAPI app only reads environment variables, tests the MySQL connection, and runs a backup function when the API is called.

## Goal

You will have:

- A FastAPI app running on `http://localhost:8000`
- A MySQL connection based on environment variables
- An API endpoint that triggers a backup
- Backup files uploaded to MinIO or S3-compatible storage
- The same backup configuration style used by this project

## Project Structure

Create a new FastAPI project:

```text
fastapi-backup-api/
├── app/
│   ├── __init__.py
│   ├── backup.py
│   └── main.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env
```

## Environment Variables

The API uses these variables:

```env
# Database Configuration
DB_HOST=mysql
DB_PORT=3306
DB_USER=root
DB_PASSWORD=root_password
DB_NAMES=fastapi_app
DB_SSL_MODE=DISABLED

# S3/MinIO Configuration
S3_ENDPOINT=http://minio:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin123
S3_BUCKET=fastapi-backups
S3_PATH_PREFIX=backups
S3_REGION=us-east-1

# Backup Settings
BACKUP_TIMEOUT=3600
```

`DB_NAMES` can contain one database or multiple comma-separated database names:

```env
DB_NAMES=database1,database2,database3
```

## 1. Dependencies

Create `requirements.txt`:

```txt
fastapi==0.115.6
uvicorn[standard]==0.34.0
pymysql==1.1.1
cryptography==44.0.0
boto3==1.35.90
```

## 2. Backup Function

Create `app/backup.py`:

```python
import gzip
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.client import Config


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def db_ssl_args() -> list[str]:
    mode = os.getenv("DB_SSL_MODE", "DISABLED").upper()

    if mode in {"DISABLED", "FALSE", "0", "NO"}:
        return ["--skip-ssl"]

    if mode in {"VERIFY_DISABLED", "REQUIRED", "TRUE", "1", "YES"}:
        return ["--ssl", "--skip-ssl-verify-server-cert"]

    if mode == "VERIFY_CA":
        ca_path = required_env("DB_SSL_CA")
        return ["--ssl", "--ssl-verify-server-cert", f"--ssl-ca={ca_path}"]

    if mode == "PREFERRED":
        return []

    raise RuntimeError(
        "Invalid DB_SSL_MODE. Use DISABLED, PREFERRED, VERIFY_DISABLED, or VERIFY_CA."
    )


def s3_client():
    return boto3.client(
        "s3",
        endpoint_url=required_env("S3_ENDPOINT"),
        aws_access_key_id=required_env("S3_ACCESS_KEY"),
        aws_secret_access_key=required_env("S3_SECRET_KEY"),
        region_name=os.getenv("S3_REGION", "us-east-1"),
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def ensure_bucket(client, bucket: str) -> None:
    existing = [item["Name"] for item in client.list_buckets().get("Buckets", [])]
    if bucket not in existing:
        client.create_bucket(Bucket=bucket)


def dump_database(database: str, output_file: Path) -> None:
    db_port = os.getenv("DB_PORT", "3306")
    timeout = int(os.getenv("BACKUP_TIMEOUT", "3600"))

    command = [
        "mysqldump",
        f"--host={required_env('DB_HOST')}",
        f"--port={db_port}",
        f"--user={required_env('DB_USER')}",
        f"--password={required_env('DB_PASSWORD')}",
        *db_ssl_args(),
        "--single-transaction",
        "--routines",
        "--triggers",
        "--no-tablespaces",
        database,
    ]

    raw_file = output_file.with_suffix("")

    with raw_file.open("wb") as dump:
        subprocess.run(command, stdout=dump, stderr=subprocess.PIPE, check=True, timeout=timeout)

    with raw_file.open("rb") as source, gzip.open(output_file, "wb") as target:
        shutil.copyfileobj(source, target)

    raw_file.unlink(missing_ok=True)


def create_backups() -> dict:
    bucket = required_env("S3_BUCKET")
    prefix = os.getenv("S3_PATH_PREFIX", "backups").strip("/")
    db_names = [db.strip() for db in required_env("DB_NAMES").split(",") if db.strip()]

    if not db_names:
        raise RuntimeError("DB_NAMES must contain at least one database name")

    client = s3_client()
    ensure_bucket(client, bucket)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    results = []

    for database in db_names:
        filename = f"{database}_{timestamp}.sql.gz"
        local_file = Path("/tmp") / filename
        s3_key = f"{prefix}/{database}/{filename}"

        try:
            dump_database(database, local_file)
            client.upload_file(str(local_file), bucket, s3_key)
            results.append({"database": database, "status": "success", "s3_key": s3_key})
        except subprocess.CalledProcessError as exc:
            error = exc.stderr.decode(errors="replace") if exc.stderr else str(exc)
            results.append({"database": database, "status": "failed", "error": error})
        except Exception as exc:
            results.append({"database": database, "status": "failed", "error": str(exc)})
        finally:
            local_file.unlink(missing_ok=True)

    failed = [item for item in results if item["status"] != "success"]

    return {
        "status": "failed" if failed else "success",
        "timestamp": timestamp,
        "results": results,
    }
```

## 3. FastAPI App

Create `app/main.py`:

```python
import pymysql
from fastapi import FastAPI, HTTPException

from app.backup import create_backups, required_env


app = FastAPI(title="MySQL Backup Trigger API")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/db-check")
def db_check():
    try:
        connection = pymysql.connect(
            host=required_env("DB_HOST"),
            port=int(required_env("DB_PORT")),
            user=required_env("DB_USER"),
            password=required_env("DB_PASSWORD"),
            connect_timeout=5,
        )
        connection.close()
        return {"status": "connected"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/backups/run")
def run_backup():
    try:
        return create_backups()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
```

## 4. Dockerfile

Create `Dockerfile`:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends default-mysql-client gzip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## 5. Docker Compose Example

Create `docker-compose.yml`:

```yaml
services:
  mysql:
    image: mysql:8.4
    container_name: backup-demo-mysql
    restart: unless-stopped
    environment:
      MYSQL_ROOT_PASSWORD: root_password
      MYSQL_DATABASE: fastapi_app
    ports:
      - "3306:3306"
    volumes:
      - mysql_data:/var/lib/mysql
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-u", "root", "-proot_password"]
      interval: 10s
      timeout: 5s
      retries: 10

  minio:
    image: minio/minio:latest
    container_name: backup-demo-minio
    restart: unless-stopped
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin123
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - minio_data:/data

  api:
    build: .
    container_name: backup-trigger-api
    restart: unless-stopped
    environment:
      DB_HOST: mysql
      DB_PORT: 3306
      DB_USER: root
      DB_PASSWORD: root_password
      DB_NAMES: fastapi_app
      DB_SSL_MODE: DISABLED

      S3_ENDPOINT: http://minio:9000
      S3_ACCESS_KEY: minioadmin
      S3_SECRET_KEY: minioadmin123
      S3_BUCKET: fastapi-backups
      S3_PATH_PREFIX: backups
      S3_REGION: us-east-1

      BACKUP_TIMEOUT: 3600
    ports:
      - "8000:8000"
    depends_on:
      mysql:
        condition: service_healthy
      minio:
        condition: service_started

volumes:
  mysql_data:
  minio_data:
```

## 6. Start the Services

```bash
docker compose up -d --build
```

## 7. Test MySQL Connection

```bash
curl http://localhost:8000/db-check
```

Expected response:

```json
{
  "status": "connected"
}
```

## 8. Trigger a Backup

```bash
curl -X POST http://localhost:8000/backups/run
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
      "s3_key": "backups/fastapi_app/fastapi_app_2026-06-17_10-30-00.sql.gz"
    }
  ]
}
```

## 9. Verify Backup in MinIO

Open MinIO console:

```text
http://localhost:9001
```

Login:

```text
Username: minioadmin
Password: minioadmin123
```

Expected object path:

```text
fastapi-backups/
└── backups/
    └── fastapi_app/
        └── fastapi_app_YYYY-MM-DD_HH-MM-SS.sql.gz
```

## Notes

- This app does not use models or schemas.
- The backup is triggered by an API call, not cron.
- `mysqldump` must be installed in the API container.
- `DB_NAMES` controls which databases are backed up.
- `DB_SSL_MODE=DISABLED` avoids self-signed certificate errors for local/internal networks.
- For production, protect `POST /backups/run` with authentication.
