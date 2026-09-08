"""Dropzone-Connector: beobachtet zwei lokale Unterordner (z.B. per Syncthing
oder Nextcloud vom Handy synchronisiert) und lädt jede neue Datei darin nach
Docspell hoch — für Belege, die nie digital ankommen (Restaurant, Parkschein,
Tankquittung: mit dem Handy fotografieren, landet automatisch in der Ablage),
sowie für den manuellen Amazon-Business-Bulk-Export.

Zwei Unterordner statt einem, weil die Firma zwischen empfangenen Belegen
(Eingang: Einkäufe/Lieferantenrechnungen) und selbst gestellten Rechnungen
(Ausgang: Rechnungen an eigene Kunden) unterscheidet — als Tag "Eingang"/
"Ausgang" an Docspell mitgegeben. Die Einsortierung in den Jahr/Monat-
Ordnerbaum unter ./data/belege-nach-monat übernimmt NICHT dieser Connector,
sondern der separate, periodisch laufende connector-mirror-sync (siehe
connectors/mirror-sync/mirror_sync.py) — der liest das tatsächliche, von
Docspells OCR erkannte Beleg-Datum aus, statt hier beim Upload nur die
Datei-mtime zu raten.

Kein Cloud-Dienst nötig: Syncthing synct direkt zwischen Handy und diesem
Server, ohne Zwischenstation bei einem Dritt-Anbieter — siehe README in
diesem Ordner für die Einrichtung.

Ablauf je Unterordner: neue Datei → hochladen → nach Erfolg nach
verarbeitet/ verschieben (nicht löschen, damit nichts verloren geht, falls
der Upload fehlschlägt oder man nochmal reinschauen will).
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import sys
import time
from pathlib import Path

# Im Docker-Image liegt "common/" direkt neben dieser Datei (vom Dockerfile so
# kopiert); in einem rohen Git-Checkout liegt es stattdessen eine Ebene höher
# unter connectors/common. Beide Fälle abdecken.
_here = Path(__file__).resolve().parent
for _candidate in (_here, _here.parent):
    if (_candidate / "common").is_dir():
        sys.path.insert(0, str(_candidate))
        break

from common.docspell_client import DocspellClient, DocspellMeta  # noqa: E402
from common.notify import notify  # noqa: E402
from common.state import ProcessedStore  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dropzone-connector")

DROPZONE_DIR = Path("/dropzone")
STATE_DB = Path("/state/dropzone.sqlite3")

# (Unterordnername, Docspell-/Mirror-"kind")
WATCHED_SUBDIRS = [("eingang", "Eingang"), ("ausgang", "Ausgang")]

IGNORED_SUFFIXES = {".tmp", ".part", ".syncthing", ".crdownload"}


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _process_subdir(subdir_name: str, kind: str, store: ProcessedStore, client: DocspellClient) -> None:
    watch_dir = DROPZONE_DIR / subdir_name
    processed_dir = watch_dir / "verarbeitet"
    failed_dir = watch_dir / "fehlgeschlagen"
    watch_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)

    source_tag = f"dropzone-{subdir_name}"

    for path in sorted(watch_dir.iterdir()):
        if not path.is_file() or path.parent != watch_dir:
            continue
        if path.suffix.lower() in IGNORED_SUFFIXES or path.name.startswith("."):
            continue

        file_hash = _file_hash(path)
        if store.is_processed(source_tag, file_hash):
            continue

        content = path.read_bytes()
        meta = DocspellMeta(tags=["Manuell", "Unsortiert", kind], folder="Manuell")
        if client.upload(path.name, content, meta):
            store.mark_processed(source_tag, file_hash)
            shutil.move(str(path), str(processed_dir / path.name))
            log.info("Verarbeitet (%s): %s", kind, path.name)
        else:
            log.warning("Upload fehlgeschlagen, verschiebe nach %s: %s", failed_dir, path.name)
            shutil.move(str(path), str(failed_dir / path.name))


def run_once(store: ProcessedStore, client: DocspellClient) -> None:
    for subdir_name, kind in WATCHED_SUBDIRS:
        _process_subdir(subdir_name, kind, store, client)


def main() -> None:
    store = ProcessedStore(STATE_DB)
    client = DocspellClient()
    interval = int(os.environ.get("DROPZONE_POLL_INTERVAL_SECONDS", "60"))
    alert_threshold = int(os.environ.get("DROPZONE_ALERT_AFTER_FAILURES", "3"))

    while True:
        try:
            run_once(store, client)
            store.record_success("dropzone")
        except Exception as exc:
            log.exception("Fehler im Dropzone-Connector-Durchlauf")
            failures = store.record_failure("dropzone")
            if store.should_alert("dropzone", alert_threshold):
                notify(
                    "Belegwirtschaft: Dropzone-Connector gestört",
                    f"{failures} Durchläufe in Folge fehlgeschlagen. Letzter Fehler: {exc}",
                    priority="high",
                )
        time.sleep(interval)


if __name__ == "__main__":
    main()
