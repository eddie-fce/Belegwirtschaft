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
from datetime import datetime
from pathlib import Path

import yaml
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Im Docker-Image liegt "common/" direkt neben dieser Datei (vom Dockerfile so
# kopiert); in einem rohen Git-Checkout (z.B. für den lokalen --login-Schritt)
# liegt es stattdessen eine Ebene höher unter connectors/common. Beide Fälle
# abdecken, damit --login ohne manuelles Kopieren funktioniert.
_here = Path(__file__).resolve().parent
for _candidate in (_here, _here.parent):
    if (_candidate / "common").is_dir():
        sys.path.insert(0, str(_candidate))
        break

from common.amount_extract import extract_amount  # noqa: E402
from common.docspell_client import DocspellClient, DocspellMeta  # noqa: E402
from common.monthly_mirror import mirror as mirror_to_month_folder  # noqa: E402
from common.notify import notify  # noqa: E402
from common.state import ProcessedStore  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gmail-connector")

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
# /secrets ist der Pfad im Docker-Container (per Volume gemountet, siehe
# docker-compose.yml) — der existiert nur dort. Für den lokalen --login-Schritt
# (ausserhalb von Docker, siehe README) auf den secrets/-Ordner neben diesem
# Skript zurückfallen, genau dort, wohin die README-Anleitung credentials.json
# legen lässt.
SECRETS_DIR = Path("/secrets") if Path("/secrets").is_dir() else Path(__file__).resolve().parent / "secrets"
STATE_DB = Path("/state/gmail.sqlite3")
CONFIG_PATH = Path("/config/sources.yaml")
MONTHLY_MIRROR_DIR = Path("/monthly")


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


def fetch_message_date(service, msg_id: str) -> datetime | None:
    """Datum, an dem die Mail bei Gmail einging — als Näherung fürs Beleg-/
    Kaufdatum für die Monatsordner-Einsortierung. Deutlich näher dran als das
    Verarbeitungsdatum (bei dem ein später nachgeholter Poll-Lauf sonst alles
    in den falschen Monat sortieren würde), auch wenn es nicht exakt das
    Rechnungsdatum selbst ist. Docspells OCR bleibt die massgebliche,
    korrigierbare Quelle innerhalb von Docspell selbst — dieser Wert steuert
    nur den Dateisystem-Spiegel."""
    msg = service.users().messages().get(userId="me", id=msg_id, format="minimal").execute()
    internal_date_ms = msg.get("internalDate")
    if not internal_date_ms:
        return None
    return datetime.fromtimestamp(int(internal_date_ms) / 1000)


def fetch_email_text(service, msg_id: str) -> str:
    """Holt den Klartext-Body einer Mail (für die Betrag-Extraktion). Best-effort:
    bevorzugt text/plain, sonst text/html roh (Regex verträgt die paar HTML-Tags
    im Umfeld einer Zahl meist problemlos)."""
    msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    parts = _walk_parts(msg.get("payload", {}))
    plain, html = "", ""
    for part in parts:
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if not data:
            continue
        text = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        if mime == "text/plain":
            plain += text
        elif mime == "text/html":
            html += text
    return plain or html


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

            # Betrag aus dem Mailtext extrahieren (best effort) — als Plausibilitäts-
            # Referenz für den später von Docspells OCR erkannten Betrag. Landet
            # sichtbar im Dateinamen und wird zusätzlich im lokalen State gespeichert.
            expected_amount, expected_currency = None, None
            try:
                email_text = fetch_email_text(service, msg_id)
                result = extract_amount(email_text)
                if result:
                    expected_amount, expected_currency = result
            except Exception:
                log.debug("Konnte Betrag aus Mailtext nicht extrahieren (Mail %s)", msg_id)

            try:
                mirror_date = fetch_message_date(service, msg_id) or datetime.now()
            except Exception:
                log.debug("Konnte Mail-Datum nicht abrufen (Mail %s), nutze heute", msg_id)
                mirror_date = datetime.now()

            # Alle bisherigen Regeln sind Einkäufe/Lieferantenrechnungen — "Eingang".
            # Für eine künftige Regel auf Ausgangsrechnungen (falls die Firma sich
            # selbst Kopien per Mail zustellt) in sources.yaml "kind: Ausgang" setzen.
            kind = rule.get("kind", "Eingang")
            meta = DocspellMeta(
                correspondent=rule.get("correspondent"),
                tags=[*rule.get("tags", []), kind],
                folder=rule.get("folder"),
            )
            ok_count = 0
            for filename, content in attachments:
                upload_name = filename
                if expected_amount:
                    stem, dot, ext = filename.rpartition(".")
                    suffix = f"_{expected_amount}{expected_currency}"
                    upload_name = f"{stem}{suffix}.{ext}" if dot else f"{filename}{suffix}"
                if client.upload(upload_name, content, meta):
                    ok_count += 1
                    mirror_to_month_folder(MONTHLY_MIRROR_DIR, upload_name, content, when=mirror_date, kind=kind)

            if ok_count == len(attachments):
                store.mark_processed(
                    "gmail", msg_id, expected_amount=expected_amount, expected_currency=expected_currency
                )
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
    alert_threshold = int(os.environ.get("GMAIL_ALERT_AFTER_FAILURES", "3"))
    while True:
        try:
            run_once(service, store, client)
            store.record_success("gmail")
        except Exception as exc:
            log.exception("Fehler im Gmail-Connector-Durchlauf")
            failures = store.record_failure("gmail")
            if store.should_alert("gmail", alert_threshold):
                notify(
                    "Belegwirtschaft: Gmail-Connector gestört",
                    f"{failures} Durchläufe in Folge fehlgeschlagen. Letzter Fehler: {exc}\n"
                    "Bitte Logs prüfen: docker compose logs connector-gmail",
                    priority="high",
                )
        time.sleep(interval)


if __name__ == "__main__":
    main()
