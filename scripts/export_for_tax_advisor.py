#!/usr/bin/env python3
"""Exportiert alle als "Rechnung" getaggten Belege eines Zeitraums als ZIP,
sortiert nach Jahr/Monat (z.B. "2026/03/2026-03-15_...pdf") — genau die
Struktur, die ein Steuerberater i.d.R. erwartet, ohne dass Docspell selbst
echte Ordner kennt (siehe README-Abschnitt "Nutzung im Alltag").

Nutzt Docspells authentifizierte Such- und Download-API über
connectors/common/docspell_query.py — gegen Docspells Quellcode verifiziert
(siehe Kommentare dort für Details, u.a. Datumsformat und Attachment- statt
Item-ID beim Download).

Nutzung (empfohlen: containerisiert über docker-compose, kein lokales Python
nötig — siehe Service "export-tax-advisor" in docker-compose.yml):
  docker compose run --rm export-tax-advisor --year 2026 --out /data/export-2026.zip
  docker compose run --rm export-tax-advisor --from 2026-01-01 --to 2026-03-31 \
      --out /data/export-q1-2026.zip

Alternativ direkt mit lokalem Python (aus dem Projekt-Root, mit installierten
Abhängigkeiten aus scripts/requirements.txt):
  python scripts/export_for_tax_advisor.py --year 2026 --out data/export-2026.zip
"""

from __future__ import annotations

import argparse
import io
import logging
import os
import sys
import zipfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "connectors" / "common"))
from date_extract import extract_date  # noqa: E402
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


def _year_month_prefix(d: date | None) -> str:
    """Baut 'JJJJ/MM' aus dem von Docspell erkannten Beleg-Datum. Items ohne
    erkanntes Datum landen in einem eigenen Sammelordner statt falsch
    sortiert zu werden."""
    if d is None:
        return "ohne-datum"
    return f"{d:%Y}/{d:%m}"


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
            # r.date kommt aus der Suche und ist serverseitig
            # coalesce(itemDate, created) - liefert also auch ohne von
            # Docspell erkanntes Datum einen Wert. Das echte, nullable
            # Datum gibt es nur über die Item-Detailsicht.
            try:
                real_date = client.get_item_date(r.item_id)
            except Exception:
                log.exception("Konnte echtes Datum für Item %s (%s) nicht laden", r.item_id, r.name)
                real_date = None

            # Fallback wie in connectors/mirror-sync/mirror_sync.py: Docspells
            # eigene Erkennung ist bei maschinell erzeugten Belegen
            # nachweislich unzuverlässig (siehe common/date_extract.py).
            if real_date is None and r.attachments:
                try:
                    text = client.get_extracted_text(r.attachments[0].id)
                    found = extract_date(text)
                except Exception:
                    found = None
                if found is not None:
                    try:
                        client.set_item_date(r.item_id, found)
                        real_date = found
                    except Exception:
                        log.exception("Konnte selbst erkanntes Datum nicht setzen für Item %s", r.item_id)

            prefix = _year_month_prefix(real_date)
            date_label = f"{real_date:%Y-%m-%d}" if real_date else "ohne-datum"
            if not r.attachments:
                log.warning("Item %s (%s) hat keine Attachments, übersprungen", r.item_id, r.name)
                continue
            for att in r.attachments:
                try:
                    content = client.download_original(att.id)
                except Exception:
                    log.exception(
                        "Download fehlgeschlagen für Attachment %s (Item %s, %s) — übersprungen",
                        att.id,
                        r.item_id,
                        r.name,
                    )
                    continue
                safe_name = f"{prefix}/{date_label}_{r.item_id}_{att.name or r.name or 'beleg'}.pdf"
                zf.writestr(safe_name, content)
                manifest_lines.append(
                    f"{prefix};{r.item_id};{att.name or r.name};{r.correspondent or ''};{date_label};{'|'.join(r.tags)}"
                )
        zf.writestr("manifest.csv", "\n".join(manifest_lines))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(buf.getvalue())
    log.info("Geschrieben: %s (nach Jahr/Monat sortiert)", out_path)


if __name__ == "__main__":
    main()
