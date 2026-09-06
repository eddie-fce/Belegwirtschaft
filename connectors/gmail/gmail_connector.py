"""Gmail-Connector: sucht Belege im Gmail-Konto nach Regeln aus sources.yaml,
lädt Anhänge (oder rendert die Mail selbst als PDF) herunter und schiebt sie
in Docspell.

Zugriff erfolgt ausschliesslich über den offiziellen OAuth2-Scope
"gmail.readonly" — der Connector kann also nichts löschen, verschieben oder
versenden, nur lesen. Das Google-OAuth-Token liegt lokal unter /secrets und
verlässt den Rechner nur für die eigentlichen Gmail-API-Aufrufe an Google.

Einmaliger Setup-Schritt (siehe README in diesem Ordner):
  1. In der Google Cloud Console ein OAuth-Client (Typ "Desktop-App") anlegen,
     Gmail-API aktivieren, credentials.json nach ./secrets/ legen.
  2. Einmal interaktiv `python gmail_connector.py --login` ausführen, um das
     Token zu erzeugen (danach läuft es headless im Container weiter).
"""

from __future__ import annotations

import base64
import fnmatch
import logging
import os
import sys
import time
from pathlib import Path

import yaml
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "common"))
from common.docspell_client import DocspellClient, DocspellMeta  # noqa: E402
from common.state import ProcessedStore  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gmail-connector")

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
SECRETS_DIR = Path("/secrets")
STATE_DB = Path("/state/gmail.sqlite3")
CONFIG_PATH = Path("/config/sources.yaml")


def load_rules() -> tuple[list[dict], list[str]]:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg.get("rules", []), cfg.get("ignore_attachment_patterns", [])


def get_credentials(interactive: bool) -> Credentials:
    token_path = SECRETS_DIR / "token.json"
    creds: Credentials | None = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json())
        return creds

    if not interactive:
        raise RuntimeError(
            "Kein gültiges Gmail-Token gefunden. Bitte einmalig lokal ausführen:\n"
            "  python gmail_connector.py --login\n"
            "und die Datei secrets/token.json in dieses Setup übernehmen."
        )

    creds_path = SECRETS_DIR / "credentials.json"
    if not creds_path.exists():
        raise RuntimeError(
            f"{creds_path} fehlt. In der Google Cloud Console ein OAuth-Client "
            "(Typ 'Desktop-App') anlegen, Gmail-API aktivieren, JSON herunterladen "
            "und hierhin legen."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
    creds = flow.run_local_server(port=0)
    token_path.write_text(creds.to_json())
    return creds


def matches_ignore(filename: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(filename.lower(), p.lower()) for p in patterns)


def fetch_attachments(service, msg_id: str, ignore_patterns: list[str]) -> list[tuple[str, bytes]]:
    msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    parts = _walk_parts(msg.get("payload", {}))
    out = []
    for part in parts:
        filename = part.get("filename") or ""
        body = part.get("body", {})
        if not filename or "attachmentId" not in body:
            continue
        if matches_ignore(filename, ignore_patterns):
            continue
        att = (
            service.users()
            .messages()
            .attachments()
            .get(userId="me", id=body["attachmentId"], messageId=msg_id)
            .execute()
        )
        data = base64.urlsafe_b64decode(att["data"])
        out.append((filename, data))
    return out


def _walk_parts(payload: dict) -> list[dict]:
    parts = payload.get("parts")
    if not parts:
        return [payload]
    out = []
    for p in parts:
        out.extend(_walk_parts(p))
    return out


def run_once(service, store: ProcessedStore, client: DocspellClient) -> None:
    rules, ignore_patterns = load_rules()
    label = os.environ.get("GMAIL_LABEL", "INBOX")

    for rule in rules:
        query = f'label:{label} {rule["query"]}'
        log.info("Regel '%s': Suche %r", rule["name"], query)

        resp = service.users().messages().list(userId="me", q=query, maxResults=50).execute()
        messages = resp.get("messages", [])

        for m in messages:
            msg_id = m["id"]
            if store.is_processed("gmail", msg_id):
                continue

            attachments = fetch_attachments(service, msg_id, ignore_patterns)
            if not attachments:
                log.info("Keine passenden Anhänge in Mail %s, überspringe", msg_id)
                store.mark_processed("gmail", msg_id)
                continue

            meta = DocspellMeta(
                correspondent=rule.get("correspondent"),
                tags=rule.get("tags", []),
                folder=rule.get("folder"),
            )
            ok_count = 0
            for filename, content in attachments:
                if client.upload(filename, content, meta):
                    ok_count += 1

            if ok_count == len(attachments):
                store.mark_processed("gmail", msg_id)
            else:
                log.warning(
                    "Nicht alle Anhänge von Mail %s hochgeladen (%d/%d) — beim "
                    "nächsten Lauf erneut versuchen",
                    msg_id,
                    ok_count,
                    len(attachments),
                )


def main() -> None:
    interactive = "--login" in sys.argv
    creds = get_credentials(interactive)
    if interactive:
        log.info("Login erfolgreich, Token gespeichert unter %s", SECRETS_DIR / "token.json")
        return

    service = build("gmail", "v1", credentials=creds)
    store = ProcessedStore(STATE_DB)
    client = DocspellClient()

    interval = int(os.environ.get("GMAIL_POLL_INTERVAL_SECONDS", "900"))
    while True:
        try:
            run_once(service, store, client)
        except Exception:
            log.exception("Fehler im Gmail-Connector-Durchlauf")
        time.sleep(interval)


if __name__ == "__main__":
    main()
