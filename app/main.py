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
        return create_backups()
    except BackupAlreadyRunning as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
