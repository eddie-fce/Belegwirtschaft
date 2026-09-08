"""Mirror-Sync: baut den durchsuchbaren Jahr/Monat-Ordnerbaum unter
./data/belege-nach-monat NICHT mehr aus einer Datums-Näherung der Connectors
beim Upload, sondern direkt aus Docspells eigenem, von der OCR erkannten
(oder in der Docspell-Oberfläche manuell korrigierten) Beleg-Datum. Das ist
das tatsächliche Rechnungs-/Kaufdatum, nicht das E-Mail-Eingangsdatum oder
die Datei-mtime eines Handyfotos — wichtig, weil der Steuerberater direkt auf
diesen Ordnerbaum zugreift und sich auf die richtige Periode verlassen muss.

Läuft periodisch gegen die normale (Nutzer-)Login-API, nicht den Integration-
Endpoint, weil dafür Suche + Originaldatei-Download nötig sind (siehe
common/docspell_query.py). Erfasst dabei ALLE Items der Collective, nicht nur
per Connector hochgeladene — auch manuell in Docspells Oberfläche eingefügte
Belege landen so automatisch im Ordnerbaum (das war vorher eine bekannte
Lücke, siehe README-Abschnitt "Nutzung im Alltag").

WICHTIG (live aufgefallen): das Datum aus der normalen Suche ist serverseitig
coalesce(itemDate, created) — Items ganz ohne von Docspell erkanntes Datum
liefern dort trotzdem einen Wert (das Upload-/Verarbeitungsdatum), nicht
unterscheidbar von einem echten Treffer. Deshalb holt dieses Skript das
tatsächliche, nullable Datum separat je Item über die Detailsicht
(client.get_item_date, siehe docspell_query.py) statt sich auf das
Suchergebnis zu verlassen.

Verhalten je Sync-Lauf:
- Attachment mit von Docspell erkanntem Datum -> Datei liegt/landet unter
  <Jahr>/<Eingang|Ausgang>/<Monat>/dateiname.
- Attachment (noch) ohne erkanntes Datum -> ohne-datum/<Eingang|Ausgang>/
  dateiname. Kein Rateversuch mit dem heutigen Datum — das würde einen alten
  Beleg im falschen Monat einsortieren. Sobald Docspell später ein Datum
  erkennt oder es manuell in der Oberfläche gesetzt wird, verschiebt der
  nächste Lauf die Datei automatisch an die richtige Stelle.
- Eingang/Ausgang wird an den vom Gmail-/Dropzone-Connector gesetzten Tags
  festgemacht, NICHT an Docspells eigenem "direction"-Feld — das setzt der
  Integration-Endpoint-Client aktuell immer fest auf "incoming"
  (siehe common/docspell_client.py, unabhängiger, für sich zu behebender
  Punkt).
- Ändert sich das erkannte Datum eines bereits gespiegelten Attachments
  (Nach-OCR oder manuelle Korrektur), wird die alte Kopie entfernt und unter
  dem neuen Pfad neu geschrieben — keine Duplikate.
- Wird ein Item in Docspell gelöscht (Papierkorb), verschwindet die
  gespiegelte Datei beim nächsten Lauf automatisch wieder.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Im Docker-Image liegt "common/" direkt neben dieser Datei (vom Dockerfile so
# kopiert); in einem rohen Git-Checkout liegt es stattdessen eine Ebene höher
# unter connectors/common. Beide Fälle abdecken.
_here = Path(__file__).resolve().parent
for _candidate in (_here, _here.parent):
    if (_candidate / "common").is_dir():
        sys.path.insert(0, str(_candidate))
        break

from common.docspell_query import DocspellQueryClient  # noqa: E402
from common.monthly_mirror import mirror as mirror_to_month_folder  # noqa: E402
from common.monthly_mirror import remove as remove_mirrored  # noqa: E402
from common.notify import notify  # noqa: E402
from common.state import ProcessedStore  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("mirror-sync")

STATE_DB = Path("/state/mirror-sync.sqlite3")
MONTHLY_MIRROR_DIR = Path("/monthly")


def _kind(tags: list[str]) -> str:
    return "Ausgang" if "Ausgang" in tags else "Eingang"


def _target_path(item_name: str, att_name: str | None, when: datetime | None, kind: str) -> Path:
    filename = att_name or item_name or "beleg.pdf"
    if when is not None:
        return MONTHLY_MIRROR_DIR / f"{when:%Y}" / kind / f"{when:%m}" / filename
    return MONTHLY_MIRROR_DIR / "ohne-datum" / kind / filename


def run_once(client: DocspellQueryClient, store: ProcessedStore) -> None:
    results = client.search("")
    seen_attachment_ids: set[str] = set()
    new_count = moved_count = unchanged_count = failed_count = 0

    for item in results:
        kind = _kind(item.tags)
        # WICHTIG: item.date aus der Suche ist serverseitig
        # coalesce(itemDate, created) — liefert also auch dann einen Wert,
        # wenn Docspell nie ein echtes Datum erkannt hat (dann eben das
        # Upload-Datum, nicht unterscheidbar von einem echten Treffer). Das
        # tatsächliche, nullable Datum gibt es nur über die Item-
        # Detailsicht (siehe docspell_query.py).
        try:
            real_date = client.get_item_date(item.item_id)
        except Exception:
            log.exception("Konnte echtes Datum für Item %s (%s) nicht laden", item.item_id, item.name)
            continue

        for att in item.attachments:
            seen_attachment_ids.add(att.id)
            desired_path = _target_path(item.name, att.name, real_date, kind)
            previous_path_str = store.get_mirrored_path(att.id)

            if previous_path_str == str(desired_path) and desired_path.exists():
                unchanged_count += 1
                continue

            try:
                content = client.download_original(att.id)
            except Exception:
                log.exception(
                    "Download fehlgeschlagen für Attachment %s (Item %s, %s)",
                    att.id,
                    item.item_id,
                    item.name,
                )
                failed_count += 1
                continue

            mirror_to_month_folder(
                MONTHLY_MIRROR_DIR, desired_path.name, content, when=real_date, kind=kind
            )

            if previous_path_str and previous_path_str != str(desired_path):
                remove_mirrored(Path(previous_path_str))
                moved_count += 1
            else:
                new_count += 1

            store.set_mirrored_path(att.id, item.item_id, str(desired_path))

    stale_ids = store.all_mirrored_attachment_ids() - seen_attachment_ids
    for att_id in stale_ids:
        path_str = store.get_mirrored_path(att_id)
        if path_str:
            remove_mirrored(Path(path_str))
        store.remove_mirrored(att_id)

    log.info(
        "Sync fertig: %d neu, %d verschoben (Datum geändert), %d unverändert, "
        "%d entfernt (in Docspell gelöscht), %d Downloads fehlgeschlagen",
        new_count,
        moved_count,
        unchanged_count,
        len(stale_ids),
        failed_count,
    )


def main() -> None:
    client = DocspellQueryClient()
    store = ProcessedStore(STATE_DB)
    interval = int(os.environ.get("MIRROR_SYNC_POLL_INTERVAL_SECONDS", "1800"))
    alert_threshold = int(os.environ.get("MIRROR_SYNC_ALERT_AFTER_FAILURES", "3"))

    while True:
        try:
            run_once(client, store)
            store.record_success("mirror-sync")
        except Exception as exc:
            log.exception("Fehler im Mirror-Sync-Durchlauf")
            failures = store.record_failure("mirror-sync")
            if store.should_alert("mirror-sync", alert_threshold):
                notify(
                    "Belegwirtschaft: Mirror-Sync gestört",
                    f"{failures} Durchläufe in Folge fehlgeschlagen. Letzter Fehler: {exc}\n"
                    "Bitte Logs prüfen: docker compose logs connector-mirror-sync",
                    priority="high",
                )
        time.sleep(interval)


if __name__ == "__main__":
    main()
