"""Sehr einfacher Alarm-Kanal über ntfy (https://ntfy.sh oder selbst gehostet:
https://github.com/binwiederhier/ntfy — letzteres, wenn auch Alarme nicht über
einen Dritt-Dienst laufen sollen).

Wenn NTFY_URL nicht gesetzt ist, ist notify() ein No-Op — Benachrichtigungen
sind also rein optional und brechen nichts, wenn sie nicht konfiguriert sind.
"""

from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger(__name__)


def notify(title: str, message: str, priority: str = "default") -> None:
    url = os.environ.get("NTFY_URL")
    topic = os.environ.get("NTFY_TOPIC")
    if not url or not topic:
        log.debug("NTFY_URL/NTFY_TOPIC nicht gesetzt, überspringe Benachrichtigung: %s", title)
        return

    try:
        requests.post(
            f"{url.rstrip('/')}/{topic}",
            data=message.encode("utf-8"),
            headers={"Title": title, "Priority": priority},
            timeout=10,
        )
    except Exception:
        log.exception("Konnte Benachrichtigung nicht senden (ntfy nicht erreichbar?)")
