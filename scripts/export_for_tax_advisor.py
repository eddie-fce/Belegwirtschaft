#!/usr/bin/env python3
"""Exportiert alle als "Rechnung" getaggten Belege eines Zeitraums als ZIP —
praktisch für die quartalsweise Abgabe an Steuerberater/DATEV-Import.

BEST-EFFORT / vor Nutzung prüfen: nutzt Docspells authentifizierte Such- und
Download-API über connectors/common/docspell_query.py, die mangels Netzwerk-
zugriff auf docspell.org beim Erstellen dieses Skripts nicht live gegen eine
laufende Docspell-Instanz getestet werden konnte (siehe Kommentare dort).
Erster Testlauf daher am besten mit einem kleinen Zeitraum, um das Ergebnis
zu prüfen, bevor es Teil eines wiederkehrenden Ablaufs wird.

Nutzung:
  python scripts/export_for_tax_advisor.py --from 2026-01-01 --to 2026-03-31 \
      --out data/export-q1-2026.zip
"""

from __future__ import annotations

import argparse
import io
import logging
import os
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "connectors" / "common"))
from docspell_query import DocspellQueryClient  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("export")


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD")
    parser.add_argument("--tag", default="Rechnung", help="Docspell-Tag, Default: Rechnung")
    parser.add_argument("--out", required=True, help="Ziel-ZIP-Datei")
    args = parser.parse_args()

    load_env_file(Path(__file__).parent.parent / ".env")

    client = DocspellQueryClient()
    query = f"tag:{args.tag} date>={args.date_from} date<={args.date_to}"
    log.info("Suche: %s", query)
    results = client.search(query)
    log.info("%d Treffer", len(results))

    if not results:
        log.warning("Keine Treffer — Zeitraum/Tag prüfen, kein ZIP erzeugt.")
        return

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        manifest_lines = ["item_id;name;correspondent;date;tags"]
        for r in results:
            try:
                content = client.download_original(r.item_id)
            except Exception:
                log.exception("Download fehlgeschlagen für Item %s (%s) — übersprungen", r.item_id, r.name)
                continue
            safe_name = f"{r.date or 'ohne-datum'}_{r.item_id}_{r.name or 'beleg'}.pdf"
            zf.writestr(safe_name, content)
            manifest_lines.append(
                f"{r.item_id};{r.name};{r.correspondent or ''};{r.date or ''};{'|'.join(r.tags)}"
            )
        zf.writestr("manifest.csv", "\n".join(manifest_lines))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(buf.getvalue())
    log.info("Geschrieben: %s", out_path)


if __name__ == "__main__":
    main()
