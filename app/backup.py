import gzip
import logging
import os
import shutil
import ssl
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

import boto3
from botocore.client import Config


logger = logging.getLogger(__name__)
backup_lock = Lock()


class BackupAlreadyRunning(RuntimeError):
    pass


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


def db_ssl_config() -> dict[str, Any] | None:
    mode = os.getenv("DB_SSL_MODE", "DISABLED").upper()

    if mode in {"DISABLED", "FALSE", "0", "NO", "PREFERRED"}:
        return None

    if mode in {"VERIFY_DISABLED", "REQUIRED", "TRUE", "1", "YES"}:
        return {"check_hostname": False, "verify_mode": ssl.CERT_NONE}

    if mode == "VERIFY_CA":
        return {"ca": required_env("DB_SSL_CA")}

    raise RuntimeError(
        "Invalid DB_SSL_MODE. Use DISABLED, PREFERRED, VERIFY_DISABLED, or VERIFY_CA."
    )


def s3_client():
    return boto3.client(
        "s3",
        endpoint_url=required_env("S3_ENDPOINT").rstrip("/"),
        aws_access_key_id=required_env("S3_ACCESS_KEY"),
        aws_secret_access_key=required_env("S3_SECRET_KEY"),
        region_name=os.getenv("S3_REGION", "us-east-1"),
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=5,
            read_timeout=5,
        ),
    )


def ensure_bucket(client, bucket: str) -> None:
    existing = [item["Name"] for item in client.list_buckets().get("Buckets", [])]
    if bucket not in existing:
        client.create_bucket(Bucket=bucket)


def check_s3_connection() -> dict[str, str]:
    try:
        client = s3_client()
        bucket = required_env("S3_BUCKET")
        client.head_bucket(Bucket=bucket)
        return {
            "status": "connected",
            "message": "S3 API connection success",
        }
    except Exception as exc:
        return {
            "status": "not_connected",
            "message": f"S3 API connection failed: {exc}",
        }


def database_names() -> list[str]:
    names = [db.strip() for db in required_env("DB_NAMES").split(",") if db.strip()]
    if not names:
        raise RuntimeError("DB_NAMES must contain at least one database name")
    return names


def max_backups_per_database() -> int:
    raw_value = os.getenv("MAX_BACKUPS_PER_DATABASE", "30")
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError("MAX_BACKUPS_PER_DATABASE must be an integer") from exc

    if value < 0:
        raise RuntimeError("MAX_BACKUPS_PER_DATABASE must be greater than or equal to 0")

    return value


def cleanup_old_backups(
    client,
    bucket: str,
    database_prefix: str,
    keep_count: int,
    uploaded_key: str,
) -> list[str]:
    if keep_count == 0:
        return []

    paginator = client.get_paginator("list_objects_v2")
    objects: list[dict[str, Any]] = []

    for page in paginator.paginate(Bucket=bucket, Prefix=database_prefix):
        objects.extend(page.get("Contents", []))

    backups = [
        item
        for item in objects
        if item.get("Key", "").endswith(".sql.gz")
    ]

    if not any(item.get("Key") == uploaded_key for item in backups):
        uploaded_object = client.head_object(Bucket=bucket, Key=uploaded_key)
        backups.append(
            {
                "Key": uploaded_key,
                "LastModified": uploaded_object["LastModified"],
            }
        )

    backups.sort(key=lambda item: item["LastModified"], reverse=True)

    old_backups = backups[keep_count:]
    deleted: list[str] = []

    for backup in old_backups:
        key = backup["Key"]
        client.delete_object(Bucket=bucket, Key=key)
        deleted.append(key)

    return deleted


def dump_database(database: str, output_file: Path) -> None:
    db_port = os.getenv("DB_PORT", "3306")
    timeout = int(os.getenv("BACKUP_TIMEOUT", "3600"))
    raw_file = output_file.with_suffix("")

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

    try:
        with raw_file.open("wb") as dump:
            subprocess.run(
                command,
                stdout=dump,
                stderr=subprocess.PIPE,
                check=True,
                timeout=timeout,
            )

        with raw_file.open("rb") as source, gzip.open(output_file, "wb") as target:
            shutil.copyfileobj(source, target)
    finally:
        raw_file.unlink(missing_ok=True)


def create_backups() -> dict[str, Any]:
    if not backup_lock.acquire(blocking=False):
        raise BackupAlreadyRunning("A backup is already running")

    try:
        bucket = required_env("S3_BUCKET")
        prefix = os.getenv("S3_PATH_PREFIX", "backups").strip("/")
        keep_count = max_backups_per_database()
        client = s3_client()
        ensure_bucket(client, bucket)

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
        results: list[dict[str, Any]] = []

        for database in database_names():
            filename = f"{database}_{timestamp}.sql.gz"
            local_file = Path("/tmp") / filename
            database_prefix = f"{prefix}/{database}/" if prefix else f"{database}/"
            s3_key = f"{database_prefix}{filename}"

            logger.info("Starting backup for database %s", database)

            try:
                dump_database(database, local_file)
                client.upload_file(str(local_file), bucket, s3_key)
                deleted = cleanup_old_backups(
                    client,
                    bucket,
                    database_prefix,
                    keep_count,
                    s3_key,
                )
                results.append(
                    {
                        "database": database,
                        "status": "success",
                        "s3_key": s3_key,
                        "deleted_old_backups": deleted,
                    }
                )
                logger.info("Backup uploaded for database %s to %s", database, s3_key)
            except subprocess.CalledProcessError as exc:
                error = exc.stderr.decode(errors="replace") if exc.stderr else str(exc)
                results.append(
                    {"database": database, "status": "failed", "error": error}
                )
                logger.exception("mysqldump failed for database %s", database)
            except Exception as exc:
                results.append(
                    {"database": database, "status": "failed", "error": str(exc)}
                )
                logger.exception("Backup failed for database %s", database)
            finally:
                local_file.unlink(missing_ok=True)

        failed = [item for item in results if item["status"] != "success"]
        return {
            "status": "failed" if failed else "success",
            "timestamp": timestamp,
            "results": results,
        }
    finally:
        backup_lock.release()
