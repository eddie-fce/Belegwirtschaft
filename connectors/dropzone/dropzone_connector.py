"""Dropzone-Connector: beobachtet zwei lokale Unterordner (z.B. per Syncthing
oder Nextcloud vom Handy synchronisiert) und lädt jede neue Datei darin nach
Docspell hoch — für Belege, die nie digital ankommen (Restaurant, Parkschein,
Tankquittung: mit dem Handy fotografieren, landet automatisch in der Ablage),
sowie für den manuellen Amazon-Business-Bulk-Export.

Zwei Unterordner statt einem, weil die Firma zwischen empfangenen Belegen
(Eingang: Einkäufe/Lieferantenrechnungen) und selbst gestellten Rechnungen
(Ausgang: Rechnungen an eigene Kunden) unterscheidet — beide landen im
gleichnamigen Zweig des Jahr/Eingang-oder-Ausgang/Monat-Ordnerbaums unter
./data/belege-nach-monat (siehe common/monthly_mirror.py):
  /dropzone/eingang/  -> ./data/belege-nach-monat/<Jahr>/Eingang/<Monat>/
  /dropzone/ausgang/  -> ./data/belege-nach-monat/<Jahr>/Ausgang/<Monat>/

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
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "common"))
from common.docspell_client import DocspellClient, DocspellMeta  # noqa: E402
from common.monthly_mirror import mirror as mirror_to_month_folder  # noqa: E402
from common.notify import notify  # noqa: E402
from common.state import ProcessedStore  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dropzone-connector")

DROPZONE_DIR = Path("/dropzone")
STATE_DB = Path("/state/dropzone.sqlite3")
MONTHLY_MIRROR_DIR = Path("/monthly")

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

        # Datei-mtime statt "jetzt" fürs Einsortieren: bei Handy-Fotos, die per
        # Syncthing synct werden, bleibt i.d.R. das Aufnahmedatum als mtime
        # erhalten (Syncthing überträgt Zeitstempel mit) — deutlich näher am
        # echten Beleg-Datum als der Zeitpunkt, an dem der Connector zufällig
        # gerade den Ordner abläuft.
        mirror_date = datetime.fromtimestamp(path.stat().st_mtime)

        content = path.read_bytes()
        meta = DocspellMeta(tags=["Manuell", "Unsortiert", kind], folder="Manuell")
        if client.upload(path.name, content, meta):
            store.mark_processed(source_tag, file_hash)
            mirror_to_month_folder(MONTHLY_MIRROR_DIR, path.name, content, when=mirror_date, kind=kind)
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
