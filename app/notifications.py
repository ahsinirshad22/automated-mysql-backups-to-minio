import json
import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Any

from app.backup import required_env


logger = logging.getLogger(__name__)


def backup_result_failed(result: dict[str, Any]) -> bool:
    if result.get("status") != "success":
        return True
    return any(item.get("status") != "success" for item in result.get("results", []))


def smtp_security() -> str:
    security = os.getenv("SMTP_SECURITY", "STARTTLS").upper()
    if security not in {"STARTTLS", "SSL", "NONE"}:
        raise RuntimeError("SMTP_SECURITY must be STARTTLS, SSL, or NONE")
    return security


def check_smtp_connection() -> dict[str, str]:
    try:
        host = required_env("SMTP_HOST")
        port = int(required_env("SMTP_PORT"))
        username = os.getenv("SMTP_USERNAME", "")
        password = os.getenv("SMTP_PASSWORD", "")
        security = smtp_security()

        if security == "SSL":
            server = smtplib.SMTP_SSL(host, port, timeout=10)
        else:
            server = smtplib.SMTP(host, port, timeout=10)

        with server:
            server.ehlo()
            if security == "STARTTLS":
                server.starttls()
                server.ehlo()
            if username or password:
                server.login(username, password)

        return {
            "status": "connected",
            "message": "SMTP connection success",
        }
    except Exception as exc:
        return {
            "status": "not_connected",
            "message": f"SMTP connection failed: {exc}",
        }


def send_failure_email(subject: str, body: str) -> None:
    host = required_env("SMTP_HOST")
    port = int(required_env("SMTP_PORT"))
    username = os.getenv("SMTP_USERNAME", "")
    password = os.getenv("SMTP_PASSWORD", "")
    from_email = required_env("SMTP_FROM_EMAIL")
    to_email = required_env("SMTP_TO_EMAIL")
    security = smtp_security()

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_email
    message["To"] = to_email
    message.set_content(body)

    if security == "SSL":
        server = smtplib.SMTP_SSL(host, port, timeout=30)
    else:
        server = smtplib.SMTP(host, port, timeout=30)

    with server:
        server.ehlo()
        if security == "STARTTLS":
            server.starttls()
            server.ehlo()
        if username or password:
            server.login(username, password)
        server.send_message(message)


def notify_backup_failure(source: str, details: Any) -> None:
    try:
        host_email = os.getenv("HOST_EMAIL", "not configured")
        subject = f"MySQL backup failed ({source})"
        body = (
            f"Backup source: {source}\n"
            f"Host email: {host_email}\n\n"
            f"Failure details:\n{json.dumps(details, indent=2, default=str)}\n"
        )
        send_failure_email(subject, body)
        logger.info("Backup failure email sent for %s", source)
    except Exception:
        logger.exception("Failed to send backup failure email for %s", source)
