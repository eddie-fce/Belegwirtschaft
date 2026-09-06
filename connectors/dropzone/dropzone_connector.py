"""Dropzone-Connector: beobachtet einen lokalen Ordner (z.B. per Syncthing oder
Nextcloud vom Handy synchronisiert) und lädt jede neue Datei darin nach
Docspell hoch — für Belege, die nie digital ankommen (Restaurant, Parkschein,
Tankquittung: mit dem Handy fotografieren, landet automatisch in der Ablage).

Kein Cloud-Dienst nötig: Syncthing synct direkt zwischen Handy und diesem
Server, ohne Zwischenstation bei einem Dritt-Anbieter — siehe README in
diesem Ordner für die Einrichtung.

Ablauf: neue Datei in /dropzone → hochladen → nach Erfolg nach
/dropzone/verarbeitet verschieben (nicht löschen, damit nichts verloren geht,
falls der Upload fehlschlägt oder man nochmal reinschauen will).
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "common"))
from common.docspell_client import DocspellClient, DocspellMeta  # noqa: E402
from common.notify import notify  # noqa: E402
from common.state import ProcessedStore  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dropzone-connector")

DROPZONE_DIR = Path("/dropzone")
PROCESSED_DIR = DROPZONE_DIR / "verarbeitet"
FAILED_DIR = DROPZONE_DIR / "fehlgeschlagen"
STATE_DB = Path("/state/dropzone.sqlite3")

IGNORED_SUFFIXES = {".tmp", ".part", ".syncthing", ".crdownload"}


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def run_once(store: ProcessedStore, client: DocspellClient) -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    FAILED_DIR.mkdir(parents=True, exist_ok=True)

    for path in sorted(DROPZONE_DIR.iterdir()):
        if not path.is_file() or path.parent != DROPZONE_DIR:
            continue
        if path.suffix.lower() in IGNORED_SUFFIXES or path.name.startswith("."):
            continue

        file_hash = _file_hash(path)
        if store.is_processed("dropzone", file_hash):
            continue

        content = path.read_bytes()
        meta = DocspellMeta(tags=["Manuell", "Unsortiert"], folder="Manuell")
        if client.upload(path.name, content, meta):
            store.mark_processed("dropzone", file_hash)
            shutil.move(str(path), str(PROCESSED_DIR / path.name))
            log.info("Verarbeitet: %s", path.name)
        else:
            log.warning("Upload fehlgeschlagen, verschiebe nach %s: %s", FAILED_DIR, path.name)
            shutil.move(str(path), str(FAILED_DIR / path.name))


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
