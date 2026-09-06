"""Amazon-Business-Connector: holt Rechnungen über die offizielle Amazon
Business API (Reconciliation API + Document API) statt per Browser-Scraping.

Das ist der grosse Unterschied zum privaten Amazon-Konto (siehe
connectors/amazon/ — der Playwright-basierte Ansatz dort bleibt als Fallback
für private Konten erhalten, wird aber für Business-Konten nicht mehr
gebraucht): Amazon Business bietet Firmenkunden eine dokumentierte,
Login-with-Amazon(LWA)-authentifizierte REST-API, mit der sich Bestell- und
Rechnungsdaten stabil und offiziell abrufen lassen — kein Session-Cookie, kein
Layout-Scraping, keine ToS-Grauzone.

ACHTUNG — Best-Effort / ungetestet gegen die Live-API:
Der Netzwerkzugriff auf developer-docs.amazon.com war beim Erstellen dieses
Codes technisch blockiert. Die grundlegenden Konzepte und Bezeichnungen unten
(Reconciliation API liefert orderId/orderLineItemId/shipmentId → invoiceNumber/
invoiceId; Document API liefert darüber das PDF) sind durch öffentlich
auffindbare Amazon-Dokutitel belegt, die *exakten* Endpunkt-Pfade, Hostnamen
und JSON-Feldnamen aber nicht live verifizierbar. Alle mit "ADJUST" markierten
Stellen bitte gegen die echte Doku prüfen, sobald ihr als Amazon-Business-API-
Entwickler registriert seid und Zugriff auf https://developer-docs.amazon.com/
amazon-business/ habt:
  - Reconciliation API: .../docs/reconciliation-api-v1-reference
  - Document API:       .../docs/document-api
  - LWA-Registrierung:  .../docs/lwa-client-secret-rotation (+ Solution Provider Portal)

Voraussetzung (einmalig, nur ihr könnt das tun — siehe README in diesem
Ordner): Registrierung als Amazon-Business-API-Entwickler (Identitätsprüfung,
Developer Registration Access Form) und ein LWA-Security-Profile mit
Client-ID/Secret.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "common"))
from common.docspell_client import DocspellClient, DocspellMeta  # noqa: E402
from common.notify import notify  # noqa: E402
from common.state import ProcessedStore  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("amazon-business-connector")

SECRETS_DIR = Path("/secrets")
TOKEN_PATH = SECRETS_DIR / "token.json"
STATE_DB = Path("/state/amazon-business.sqlite3")

LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"
LWA_AUTHORIZE_URL = "https://www.amazon.com/ap/oa"  # ADJUST: je nach Marketplace ggf. anderer Host

# ADJUST: Basis-URL der Business-API ist regionsabhängig (Nordamerika/Europa/
# Fernost) — exakten Hostnamen aus der Doku übernehmen, sobald verfügbar.
API_BASE_URL = os.environ.get("AMAZON_BUSINESS_API_BASE_URL", "https://api.business.amazon.eu")


class AmazonBusinessAuthError(RuntimeError):
    pass


def _client_id() -> str:
    return os.environ["AMAZON_BUSINESS_CLIENT_ID"]


def _client_secret() -> str:
    return os.environ["AMAZON_BUSINESS_CLIENT_SECRET"]


def login_flow() -> None:
    """Einmaliger, interaktiver OAuth2-Consent (Authorization Code Grant, wie
    bei Login with Amazon üblich). Läuft lokal, nicht im Container, weil ein
    Browser gebraucht wird."""
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    redirect_uri = os.environ.get("AMAZON_BUSINESS_REDIRECT_URI", "http://localhost:8765/callback")
    scope = os.environ.get("AMAZON_BUSINESS_SCOPE", "business:reports")  # ADJUST: exakten Scope-Namen prüfen

    auth_url = (
        f"{LWA_AUTHORIZE_URL}?client_id={_client_id()}&scope={scope}"
        f"&response_type=code&redirect_uri={redirect_uri}"
    )
    print(
        "\n>>> Im Browser öffnen und mit dem Amazon-Business-Konto einloggen:\n"
        f"{auth_url}\n"
        ">>> Nach der Zustimmung leitet Amazon auf redirect_uri weiter — der 'code'-Parameter\n"
        ">>> steht dann in der Adresszeile. Den Wert hier einfügen:\n"
    )
    code = input("code=").strip()

    resp = requests.post(
        LWA_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": _client_id(),
            "client_secret": _client_secret(),
            "redirect_uri": redirect_uri,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise AmazonBusinessAuthError(f"Token-Austausch fehlgeschlagen ({resp.status_code}): {resp.text[:300]}")

    data = resp.json()
    TOKEN_PATH.write_text(_to_json(data))
    log.info("Login erfolgreich, Refresh-Token gespeichert unter %s", TOKEN_PATH)


def _to_json(obj: dict) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)


class AmazonBusinessClient:
    def __init__(self) -> None:
        if not TOKEN_PATH.exists():
            raise AmazonBusinessAuthError(
                f"{TOKEN_PATH} fehlt. Bitte einmalig lokal ausführen:\n"
                "  python amazon_business_connector.py --login"
            )
        import json

        self._token_data = json.loads(TOKEN_PATH.read_text())
        self._access_token: str | None = None
        self._access_token_expires_at: float = 0
        self.session = requests.Session()

    def _refresh_access_token(self) -> str:
        resp = requests.post(
            LWA_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._token_data["refresh_token"],
                "client_id": _client_id(),
                "client_secret": _client_secret(),
            },
            timeout=30,
        )
        if resp.status_code != 200:
            raise AmazonBusinessAuthError(
                f"Token-Refresh fehlgeschlagen ({resp.status_code}): {resp.text[:300]}. "
                "Falls das Refresh-Token widerrufen wurde: erneut 'python "
                "amazon_business_connector.py --login' ausführen."
            )
        data = resp.json()
        self._access_token = data["access_token"]
        self._access_token_expires_at = time.time() + data.get("expires_in", 3600) - 60
        return self._access_token

    def _headers(self) -> dict:
        if not self._access_token or time.time() >= self._access_token_expires_at:
            self._refresh_access_token()
        return {"Authorization": f"Bearer {self._access_token}", "Accept": "application/json"}

    def list_transactions(self, date_from: str, date_to: str) -> list[dict]:
        """Liefert Business-Transaktionen (orderId/orderLineItemId/shipmentId etc.)
        im Zeitraum. ADJUST: Pfad/Query-Parameter gegen
        reconciliation-api-v1-reference prüfen."""
        resp = self.session.get(
            f"{API_BASE_URL}/reconciliation/2020-08-01/transactions",  # ADJUST
            headers=self._headers(),
            params={"startDate": date_from, "endDate": date_to},
            timeout=60,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Transaktionsabruf fehlgeschlagen ({resp.status_code}): {resp.text[:300]}")
        return resp.json().get("transactions", [])  # ADJUST: exakter Feldname

    def get_invoice_reference(self, order_id: str, line_item_id: str, shipment_id: str) -> dict | None:
        """Löst orderId/orderLineItemId/shipmentId zu invoiceNumber/invoiceId auf.
        ADJUST: Pfad gegen retrieving-invoice-details prüfen."""
        resp = self.session.get(
            f"{API_BASE_URL}/reconciliation/2020-08-01/invoiceDetails",  # ADJUST
            headers=self._headers(),
            params={"orderId": order_id, "orderLineItemId": line_item_id, "shipmentId": shipment_id},
            timeout=30,
        )
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise RuntimeError(f"Rechnungsreferenz-Abruf fehlgeschlagen ({resp.status_code}): {resp.text[:300]}")
        return resp.json()

    def download_invoice(self, invoice_id: str) -> bytes:
        """ADJUST: Pfad/Response-Typ gegen document-api prüfen (ggf. liefert die
        API eine signierte Download-URL statt der Bytes direkt — dann hier
        einen zweiten GET auf diese URL ergänzen)."""
        resp = self.session.get(
            f"{API_BASE_URL}/documents/2020-08-01/invoices/{invoice_id}",  # ADJUST
            headers={**self._headers(), "Accept": "application/pdf"},
            timeout=60,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Rechnungsdownload fehlgeschlagen ({resp.status_code}) für {invoice_id}")
        return resp.content


def run_once(client: AmazonBusinessClient, store: ProcessedStore, docspell: DocspellClient) -> None:
    lookback_days = int(os.environ.get("AMAZON_BUSINESS_LOOKBACK_DAYS", "45"))
    date_from = (datetime.utcnow() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    date_to = datetime.utcnow().strftime("%Y-%m-%d")

    transactions = client.list_transactions(date_from, date_to)
    log.info("%d Transaktionen im Zeitraum %s..%s gefunden", len(transactions), date_from, date_to)

    for tx in transactions:
        order_id = tx.get("orderId")  # ADJUST: exakte Feldnamen
        line_item_id = tx.get("orderLineItemId")
        shipment_id = tx.get("shipmentId")
        if not order_id or not line_item_id:
            continue

        external_id = f"{order_id}:{line_item_id}"
        if store.is_processed("amazon-business", external_id):
            continue

        ref = client.get_invoice_reference(order_id, line_item_id, shipment_id)
        if not ref or not ref.get("invoiceId"):
            log.info("Keine Rechnung für %s gefunden (evtl. noch nicht ausgestellt)", external_id)
            continue

        content = client.download_invoice(ref["invoiceId"])
        meta = DocspellMeta(
            correspondent="Amazon Business",
            tags=["Rechnung", "Online-Shopping"],
            folder="Amazon",
            document_date=ref.get("invoiceDate"),
        )
        if docspell.upload(f"amazon-business-{ref['invoiceId']}.pdf", content, meta):
            store.mark_processed("amazon-business", external_id)


def main() -> None:
    if "--login" in sys.argv:
        login_flow()
        return

    client = AmazonBusinessClient()
    store = ProcessedStore(STATE_DB)
    docspell = DocspellClient()
    interval = int(os.environ.get("AMAZON_BUSINESS_POLL_INTERVAL_SECONDS", "21600"))
    alert_threshold = int(os.environ.get("AMAZON_BUSINESS_ALERT_AFTER_FAILURES", "3"))

    while True:
        try:
            run_once(client, store, docspell)
            store.record_success("amazon-business")
        except Exception as exc:
            log.exception("Fehler im Amazon-Business-Connector-Durchlauf")
            failures = store.record_failure("amazon-business")
            if store.should_alert("amazon-business", alert_threshold):
                notify(
                    "Belegwirtschaft: Amazon-Business-Connector gestört",
                    f"{failures} Durchläufe in Folge fehlgeschlagen. Letzter Fehler: {exc}\n"
                    "Häufigste Ursache: Refresh-Token widerrufen → 'python "
                    "amazon_business_connector.py --login' erneut ausführen. Sonst: "
                    "API-Endpunkte in amazon_business_connector.py gegen die aktuelle "
                    "Amazon-Business-API-Doku prüfen (ADJUST-Kommentare).",
                    priority="high",
                )
        time.sleep(interval)


if __name__ == "__main__":
    main()
