#!/usr/bin/env python3
"""Exportiert alle als "Rechnung" getaggten Belege eines Zeitraums als ZIP,
sortiert nach Jahr/Monat (z.B. "2026/03/2026-03-15_...pdf") — genau die
Struktur, die ein Steuerberater i.d.R. erwartet, ohne dass Docspell selbst
echte Ordner kennt (siehe README-Abschnitt "Nutzung im Alltag").

BEST-EFFORT / vor Nutzung prüfen: nutzt Docspells authentifizierte Such- und
Download-API über connectors/common/docspell_query.py, die mangels Netzwerk-
zugriff auf docspell.org beim Erstellen dieses Skripts nicht live gegen eine
laufende Docspell-Instanz getestet werden konnte (siehe Kommentare dort).
Erster Testlauf daher am besten mit einem kleinen Zeitraum, um das Ergebnis
zu prüfen, bevor es Teil eines wiederkehrenden Ablaufs wird.

Nutzung:
  # Ganzes Jahr auf einmal (deckt den üblichen Fall "Steuerberater will 2026"):
  python scripts/export_for_tax_advisor.py --year 2026 --out data/export-2026.zip

  # Oder ein beliebiger Zeitraum:
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


def _year_month_prefix(date_str: str | None) -> str:
    """Baut 'JJJJ/MM' aus einem Docspell-Datum. Docspell liefert Daten laut
    öffentlich bekanntem Schema als ISO-String (z.B. '2026-03-15' oder mit
    Zeitanteil '2026-03-15T00:00:00Z') — nicht live gegen die API verifiziert,
    siehe Hinweis am Dateianfang. Fällt bei unbekanntem Format auf einen
    Sammelordner zurück, statt falsch zu sortieren."""
    if not date_str or len(date_str) < 7:
        return "ohne-datum"
    year, month = date_str[:4], date_str[5:7]
    if not (year.isdigit() and month.isdigit()):
        return "ohne-datum"
    return f"{year}/{month}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, help="Ganzes Jahr exportieren, z.B. 2026 (Alternative zu --from/--to)")
    parser.add_argument("--from", dest="date_from", help="YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", help="YYYY-MM-DD")
    parser.add_argument("--tag", default="Rechnung", help="Docspell-Tag, Default: Rechnung")
    parser.add_argument("--out", required=True, help="Ziel-ZIP-Datei")
    args = parser.parse_args()

    if args.year:
        date_from, date_to = f"{args.year}-01-01", f"{args.year}-12-31"
    elif args.date_from and args.date_to:
        date_from, date_to = args.date_from, args.date_to
    else:
        parser.error("Entweder --year ODER --from/--to zusammen angeben.")
        return

    load_env_file(Path(__file__).parent.parent / ".env")

    client = DocspellQueryClient()
    query = f"tag:{args.tag} date>={date_from} date<={date_to}"
    log.info("Suche: %s", query)
    results = client.search(query)
    log.info("%d Treffer", len(results))

    if not results:
        log.warning("Keine Treffer — Zeitraum/Tag prüfen, kein ZIP erzeugt.")
        return

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        manifest_lines = ["jahr/monat;item_id;name;correspondent;date;tags"]
        for r in results:
            try:
                content = client.download_original(r.item_id)
            except Exception:
                log.exception("Download fehlgeschlagen für Item %s (%s) — übersprungen", r.item_id, r.name)
                continue
            prefix = _year_month_prefix(r.date)
            safe_name = f"{prefix}/{r.date or 'ohne-datum'}_{r.item_id}_{r.name or 'beleg'}.pdf"
            zf.writestr(safe_name, content)
            manifest_lines.append(
                f"{prefix};{r.item_id};{r.name};{r.correspondent or ''};{r.date or ''};{'|'.join(r.tags)}"
            )
        zf.writestr("manifest.csv", "\n".join(manifest_lines))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(buf.getvalue())
    log.info("Geschrieben: %s (nach Jahr/Monat sortiert)", out_path)


if __name__ == "__main__":
    main()
