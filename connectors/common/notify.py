"""Alarm-Kanäle für gestörte Connectors: ntfy (Push, https://ntfy.sh oder
selbst gehostet) und/oder E-Mail per SMTP — beide unabhängig voneinander
konfigurierbar, notify() schickt über alle, die gesetzt sind. Ohne
NTFY_URL/NTFY_TOPIC bzw. SMTP_HOST/NOTIFY_EMAIL_TO ist der jeweilige Kanal
einfach aus (kein Fehler) — Benachrichtigungen sind also rein optional.

E-Mail läuft bewusst über ein eigenes SMTP-Konto (z.B. ein Gmail
"App-Passwort"), NICHT über den Gmail-Connector-OAuth-Token — der ist
absichtlich rein lesend (gmail.readonly, siehe gmail_connector.py) und kann
daher keine Mails verschicken.
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.text import MIMEText

import requests

log = logging.getLogger(__name__)


def notify(title: str, message: str, priority: str = "default") -> None:
    _notify_ntfy(title, message, priority)
    _notify_email(title, message)


def _notify_ntfy(title: str, message: str, priority: str) -> None:
    url = os.environ.get("NTFY_URL")
    topic = os.environ.get("NTFY_TOPIC")
    if not url or not topic:
        return

    try:
        requests.post(
            f"{url.rstrip('/')}/{topic}",
            data=message.encode("utf-8"),
            headers={"Title": title, "Priority": priority},
            timeout=10,
        )
    except Exception:
        log.exception("Konnte ntfy-Benachrichtigung nicht senden (ntfy nicht erreichbar?)")


def _notify_email(title: str, message: str) -> None:
    host = os.environ.get("SMTP_HOST")
    to_addr = os.environ.get("NOTIFY_EMAIL_TO")
    if not host or not to_addr:
        return

    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    from_addr = os.environ.get("SMTP_FROM") or user or "belegwirtschaft@localhost"

    msg = MIMEText(message, "plain", "utf-8")
    msg["Subject"] = f"[Belegwirtschaft] {title}"
    msg["From"] = from_addr
    msg["To"] = to_addr

    try:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.starttls()
            if user and password:
                server.login(user, password)
            server.sendmail(from_addr, [to_addr], msg.as_string())
    except Exception:
        log.exception("Konnte E-Mail-Benachrichtigung nicht senden (SMTP-Zugangsdaten prüfen?)")
