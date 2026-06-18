import hmac
import logging
import os
from html import escape

import pymysql
from fastapi import FastAPI, Header, HTTPException, status
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv

from app.backup import (
    BackupAlreadyRunning,
    check_s3_connection,
    create_backups,
    db_ssl_config,
    required_env,
)
from app.notifications import backup_result_failed, notify_backup_failure
from app.notifications import check_smtp_connection
from app.scheduler import scheduler_status, start_scheduler, stop_scheduler


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


def check_database_connection() -> dict[str, str]:
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
        return {
            "status": "connected",
            "message": "Database connection success",
        }
    except Exception as exc:
        return {
            "status": "not_connected",
            "message": f"Database connection failed: {exc}",
        }


def service_status() -> dict:
    return {
        "database_connection": check_database_connection(),
        "s3_api_connection": check_s3_connection(),
        "smtp_connection": check_smtp_connection(),
        "cron_status": scheduler_status(),
    }


def status_class(status_value: str) -> str:
    if status_value in {"connected", "running"}:
        return "ok"
    return "bad"


def render_status_card(title: str, status_value: str, message: str) -> str:
    css_class = status_class(status_value)
    label = escape(status_value.replace("_", " ").title())
    return f"""
    <section class="card {css_class}">
        <div class="card-title">{escape(title)}</div>
        <div class="status-row">
            <span class="dot"></span>
            <span class="status-text">{label}</span>
        </div>
        <p>{escape(message)}</p>
    </section>
    """


@app.get("/", response_class=HTMLResponse)
def status_page():
    data = service_status()
    cron = data["cron_status"]
    cron_message = (
        f"Schedule: {cron.get('schedule') or 'not configured'} | "
        f"Timezone: {cron.get('timezone') or 'not configured'} | "
        f"Next run: {cron.get('next_run_time') or 'not scheduled'}"
    )
    cards = "\n".join(
        [
            render_status_card(
                "Database Connection",
                data["database_connection"]["status"],
                data["database_connection"]["message"],
            ),
            render_status_card(
                "S3 API Connection",
                data["s3_api_connection"]["status"],
                data["s3_api_connection"]["message"],
            ),
            render_status_card(
                "SMTP Connection",
                data["smtp_connection"]["status"],
                data["smtp_connection"]["message"],
            ),
            render_status_card(
                "Cron Status",
                cron["status"],
                cron_message,
            ),
        ]
    )

    return f"""
    <!doctype html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>MySQL Backup Service Status</title>
        <style>
            :root {{
                color-scheme: light;
                --bg: #f5f7fb;
                --text: #172033;
                --muted: #657089;
                --panel: #ffffff;
                --border: #dbe2ee;
                --ok: #14834f;
                --ok-bg: #e9f7ef;
                --bad: #b42318;
                --bad-bg: #fff0ee;
            }}
            * {{ box-sizing: border-box; }}
            body {{
                margin: 0;
                min-height: 100vh;
                font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                background: var(--bg);
                color: var(--text);
            }}
            main {{
                width: min(1120px, calc(100% - 32px));
                margin: 0 auto;
                padding: 40px 0;
            }}
            header {{
                display: flex;
                justify-content: space-between;
                align-items: flex-end;
                gap: 20px;
                margin-bottom: 24px;
            }}
            h1 {{
                margin: 0 0 8px;
                font-size: 32px;
                line-height: 1.1;
            }}
            .subtitle {{
                margin: 0;
                color: var(--muted);
                font-size: 15px;
            }}
            .badge {{
                border: 1px solid var(--border);
                background: var(--panel);
                border-radius: 8px;
                padding: 8px 10px;
                color: var(--muted);
                white-space: nowrap;
                font-size: 13px;
            }}
            .grid {{
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 16px;
            }}
            .card {{
                background: var(--panel);
                border: 1px solid var(--border);
                border-radius: 8px;
                padding: 20px;
                min-height: 164px;
                box-shadow: 0 10px 30px rgba(24, 39, 75, 0.06);
            }}
            .card-title {{
                font-size: 13px;
                font-weight: 700;
                letter-spacing: 0.04em;
                text-transform: uppercase;
                color: var(--muted);
                margin-bottom: 16px;
            }}
            .status-row {{
                display: flex;
                align-items: center;
                gap: 10px;
                margin-bottom: 14px;
            }}
            .dot {{
                width: 12px;
                height: 12px;
                border-radius: 50%;
                flex: 0 0 auto;
            }}
            .status-text {{
                font-size: 22px;
                font-weight: 750;
            }}
            .card p {{
                margin: 0;
                color: var(--muted);
                line-height: 1.5;
                overflow-wrap: anywhere;
            }}
            .ok {{ border-color: rgba(20, 131, 79, 0.35); }}
            .ok .dot {{ background: var(--ok); box-shadow: 0 0 0 5px var(--ok-bg); }}
            .ok .status-text {{ color: var(--ok); }}
            .bad {{ border-color: rgba(180, 35, 24, 0.35); }}
            .bad .dot {{ background: var(--bad); box-shadow: 0 0 0 5px var(--bad-bg); }}
            .bad .status-text {{ color: var(--bad); }}
            @media (max-width: 760px) {{
                header {{ display: block; }}
                .badge {{ display: inline-block; margin-top: 16px; }}
                .grid {{ grid-template-columns: 1fr; }}
                h1 {{ font-size: 27px; }}
            }}
        </style>
    </head>
    <body>
        <main>
            <header>
                <div>
                    <h1>MySQL Backup Service</h1>
                    <p class="subtitle">Live status for database, S3, SMTP, and automated backup scheduling.</p>
                </div>
                <div class="badge">Status dashboard</div>
            </header>
            <div class="grid">
                {cards}
            </div>
        </main>
    </body>
    </html>
    """


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

    db_status = check_database_connection()
    if db_status["status"] != "connected":
        raise HTTPException(status_code=500, detail=db_status["message"])
    return {"status": "connected"}


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
