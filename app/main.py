import hmac
import logging
import os

import pymysql
from fastapi import FastAPI, Header, HTTPException, status
from dotenv import load_dotenv

from app.backup import (
    BackupAlreadyRunning,
    create_backups,
    db_ssl_config,
    required_env,
)
from app.notifications import backup_result_failed, notify_backup_failure
from app.scheduler import start_scheduler, stop_scheduler


load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(title="MySQL Backup Trigger API")


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    try:
        expected = required_env("BACKUP_API_KEY")
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key",
        )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.on_event("startup")
def startup():
    start_scheduler()


@app.on_event("shutdown")
def shutdown():
    stop_scheduler()


@app.get("/db-check")
def db_check(x_api_key: str | None = Header(default=None)):
    require_api_key(x_api_key)

    try:
        connection = pymysql.connect(
            host=required_env("DB_HOST"),
            port=int(os.getenv("DB_PORT", "3306")),
            user=required_env("DB_USER"),
            password=required_env("DB_PASSWORD"),
            connect_timeout=5,
            ssl=db_ssl_config(),
        )
        connection.close()
        return {"status": "connected"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/backups/run")
def run_backup(x_api_key: str | None = Header(default=None)):
    require_api_key(x_api_key)

    try:
        result = create_backups()
        if backup_result_failed(result):
            notify_backup_failure("manual", result)
        return result
    except BackupAlreadyRunning as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        notify_backup_failure("manual", {"error": str(exc)})
        raise HTTPException(status_code=500, detail=str(exc)) from exc
