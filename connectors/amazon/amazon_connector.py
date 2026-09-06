"""Amazon-Connector: loggt sich mit einer zuvor gespeicherten Browser-Session
(deine eigene, manuell erstellte Session — keine Passwort-Automatisierung, kein
Umgehen von Login/2FA) bei amazon.<tld> ein und lädt Rechnungen aus der
Bestellhistorie herunter.

WICHTIG — bitte vor Nutzung lesen (siehe auch README in diesem Ordner):
  - Es gibt keine offizielle, stabile API für Bestellhistorie/Rechnungen von
    Amazon-Privatkonten. Dieser Connector automatisiert exakt das, was du auch
    manuell im Browser tun würdest (eingeloggt Rechnungen aufrufen), über
    Playwright. Amazon ändert das Seitenlayout gelegentlich — dann brechen die
    CSS-Selektoren unten und müssen angepasst werden (deshalb alle an einer
    Stelle oben zusammengefasst).
  - Nutze das nur für dein eigenes Konto, in normalem Tempo (keine Parallel-
    Requests, kleine Pausen) — es ist als persönliches Backup-/Archivierungs-
    Werkzeug gedacht, nicht als Scraper für fremde Daten.
  - Manche Bestellungen (v.a. Marktplatz-Verkäufer, digitale Güter) haben keine
    klassische PDF-Rechnung, sondern nur eine Bestelldetails-Seite. Für diese
    Fälle rendert der Connector ersatzweise die Bestelldetails-Seite als PDF.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "common"))
from common.docspell_client import DocspellClient, DocspellMeta  # noqa: E402
from common.notify import notify  # noqa: E402
from common.state import ProcessedStore  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("amazon-connector")

SECRETS_DIR = Path("/secrets")
STORAGE_STATE_PATH = SECRETS_DIR / "storage_state.json"
STATE_DB = Path("/state/amazon.sqlite3")

# --- CSS-Selektoren / URLs — hier anpassen, falls Amazon das Layout ändert ---
ORDER_HISTORY_PATH = "/gp/css/order-history"
ORDER_CARD_SELECTOR = "div.order-card, div.js-order-card"
ORDER_ID_ATTR_SELECTOR = "bdi"  # enthält meist die Bestellnummer im order-card
INVOICE_LINK_TEXT_PATTERNS = [
    re.compile(r"rechnung", re.IGNORECASE),
    re.compile(r"invoice", re.IGNORECASE),
]
ORDER_DETAILS_LINK_TEXT_PATTERNS = [
    re.compile(r"bestelldetails", re.IGNORECASE),
    re.compile(r"order details", re.IGNORECASE),
]
# -----------------------------------------------------------------------------


def domain() -> str:
    return os.environ.get("AMAZON_DOMAIN", "amazon.de")


def base_url() -> str:
    return f"https://www.{domain()}"


def login_flow() -> None:
    """Interaktiver, einmaliger Login. Öffnet ein sichtbares Browser-Fenster,
    in dem DU dich selbst einloggst (inkl. 2FA/Captcha) — der Connector tippt
    hier nichts automatisch ein. Danach wird die Session gespeichert."""
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(f"{base_url()}/gp/sign-in.html")
        print(
            "\n>>> Bitte im geöffneten Fenster ganz normal bei Amazon einloggen "
            "(inkl. 2FA falls aktiv).\n"
            ">>> Danach hier im Terminal ENTER drücken, sobald du auf deiner "
            "Bestellübersicht bist.\n"
        )
        input()
        context.storage_state(path=str(STORAGE_STATE_PATH))
        browser.close()
    log.info("Session gespeichert unter %s", STORAGE_STATE_PATH)


def _extract_order_ids(page: Page) -> list[str]:
    cards = page.query_selector_all(ORDER_CARD_SELECTOR)
    ids = []
    for card in cards:
        text = card.inner_text()
        m = re.search(r"(\d{3}-\d{7}-\d{7})", text)  # Standard-Amazon-Bestellnummernformat
        if m:
            ids.append(m.group(1))
    return ids


def _download_invoice_for_order(page: Page, order_id: str) -> bytes | None:
    """Sucht auf der aktuellen Order-History-Seite den Rechnungslink für eine
    Bestellung und lädt ihn herunter. Fällt auf die Bestelldetails-Seite als
    PDF-Rendering zurück, falls keine klassische Rechnung existiert."""
    links = page.query_selector_all("a")
    for link in links:
        text = (link.inner_text() or "").strip()
        if not text:
            continue
        if any(p.search(text) for p in INVOICE_LINK_TEXT_PATTERNS):
            try:
                with page.expect_download(timeout=15000) as dl_info:
                    link.click()
                download = dl_info.value
                path = download.path()
                if path:
                    return Path(path).read_bytes()
            except Exception:
                log.debug("Kein Direkt-Download bei Link %r für %s, versuche Fallback", text, order_id)

    # Fallback: Bestelldetails-Seite als PDF rendern
    for link in links:
        text = (link.inner_text() or "").strip()
        if any(p.search(text) for p in ORDER_DETAILS_LINK_TEXT_PATTERNS):
            href = link.get_attribute("href")
            if not href:
                continue
            detail_page = page.context.new_page()
            detail_page.goto(href if href.startswith("http") else base_url() + href)
            pdf_bytes = detail_page.pdf(print_background=True)
            detail_page.close()
            return pdf_bytes

    log.warning("Für Bestellung %s weder Rechnung noch Bestelldetails gefunden", order_id)
    return None


def run_once(store: ProcessedStore, client: DocspellClient) -> None:
    if not STORAGE_STATE_PATH.exists():
        raise RuntimeError(
            f"{STORAGE_STATE_PATH} fehlt. Bitte einmalig lokal ausführen:\n"
            "  python amazon_connector.py --login"
        )

    lookback_days = int(os.environ.get("AMAZON_ORDER_LOOKBACK_DAYS", "45"))
    cutoff = datetime.utcnow() - timedelta(days=lookback_days)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(STORAGE_STATE_PATH))
        page = context.new_page()
        page.goto(f"{base_url()}{ORDER_HISTORY_PATH}")

        if "signin" in page.url or "ap/signin" in page.url:
            browser.close()
            raise RuntimeError(
                "Amazon-Session ist abgelaufen oder ungültig. Bitte erneut ausführen:\n"
                "  python amazon_connector.py --login"
            )

        order_ids = _extract_order_ids(page)
        log.info("%d Bestellungen auf der aktuellen Seite gefunden", len(order_ids))
        if not order_ids:
            # Kein harter Fehler (evtl. wirklich keine neuen Bestellungen), aber
            # verdächtig genug, um bei Wiederholung zu alarmieren — typischerweise
            # ein Zeichen für ein geändertes Amazon-Layout (CSS-Selektoren oben
            # in dieser Datei prüfen).
            streak = store.record_failure("amazon_empty")
            if store.should_alert("amazon_empty", int(os.environ.get("AMAZON_ALERT_AFTER_EMPTY_RUNS", "3"))):
                notify(
                    "Belegwirtschaft: Amazon-Connector findet keine Bestellungen mehr",
                    f"{streak} Durchläufe in Folge ohne gefundene Bestellungen. "
                    "Vermutlich hat Amazon das Seitenlayout geändert — CSS-Selektoren "
                    "in amazon_connector.py prüfen, oder Session mit --login erneuern.",
                    priority="high",
                )
        else:
            store.record_success("amazon_empty")

        for order_id in order_ids:
            if store.is_processed("amazon", order_id):
                continue

            content = _download_invoice_for_order(page, order_id)
            if content is None:
                continue

            meta = DocspellMeta(
                correspondent="Amazon",
                tags=["Rechnung", "Online-Shopping"],
                folder="Amazon",
            )
            if client.upload(f"amazon-{order_id}.pdf", content, meta):
                store.mark_processed("amazon", order_id)

            time.sleep(2)  # nicht wie ein Scraper auftreten — Pause zwischen Bestellungen

        browser.close()

    _ = cutoff  # aktuell nur für spätere Datumsfilterung auf der Listenseite vorgesehen


def main() -> None:
    if "--login" in sys.argv:
        login_flow()
        return

    store = ProcessedStore(STATE_DB)
    client = DocspellClient()
    interval = int(os.environ.get("AMAZON_POLL_INTERVAL_SECONDS", "21600"))

    alert_threshold = int(os.environ.get("AMAZON_ALERT_AFTER_FAILURES", "3"))
    while True:
        try:
            run_once(store, client)
            store.record_success("amazon")
        except Exception as exc:
            log.exception("Fehler im Amazon-Connector-Durchlauf")
            failures = store.record_failure("amazon")
            if store.should_alert("amazon", alert_threshold):
                notify(
                    "Belegwirtschaft: Amazon-Connector gestört",
                    f"{failures} Durchläufe in Folge fehlgeschlagen. Letzter Fehler: {exc}\n"
                    "Meist bedeutet das: Session abgelaufen → 'python amazon_connector.py "
                    "--login' erneut ausführen.",
                    priority="high",
                )
        time.sleep(interval)


if __name__ == "__main__":
    main()
