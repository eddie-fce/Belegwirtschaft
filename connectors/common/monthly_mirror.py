"""Spiegelt jede hochgeladene Datei zusätzlich zu Docspell in einen echten,
per File Station durchsuchbaren Jahr/Monat-Ordnerbaum — für den Steuerberater,
der eine gewohnte Ordnerstruktur statt eines Docspell-Logins erwartet.

Läuft parallel zu Docspell, nicht als Ersatz: Docspell bleibt die
durchsuchbare/getaggte Ablage, dieser Ordnerbaum ist eine reine
Sichtbarkeits-Kopie fürs Dateisystem.

Sortiert nach dem von den Connectors übergebenen `when` — bewusst NICHT nach
dem Verarbeitungszeitpunkt, sonst würde ein verspätet nachgeholter Poll-Lauf
oder ein erst Wochen später gescannter Beleg im falschen Monat landen. Die
Connectors versuchen jeweils die beste verfügbare Näherung ans echte
Beleg-Datum ohne auf Docspells (asynchrone) OCR zu warten: beim Gmail-
Connector das Mail-Eingangsdatum, beim Dropzone-Connector die Datei-mtime
(bei Handy-Fotos i.d.R. das Aufnahmedatum). `when=None` (Fallback: jetzt) nur,
wenn wirklich keine bessere Quelle verfügbar ist.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)


def mirror(base_dir: Path, filename: str, content: bytes, when: datetime | None = None) -> Path:
    """Schreibt `content` unter base_dir/<Jahr>/<Monat>/<filename>. Bei einem
    Namenskonflikt (z.B. zwei Belege mit identischem Dateinamen im selben
    Monat) wird ein Zähler an den Dateinamen angehängt, statt zu überschreiben."""
    when = when or datetime.now()
    target_dir = base_dir / f"{when:%Y}" / f"{when:%m}"
    target_dir.mkdir(parents=True, exist_ok=True)

    target = target_dir / filename
    if target.exists():
        stem, dot, ext = filename.rpartition(".")
        counter = 2
        while target.exists():
            candidate = f"{stem}_{counter}.{ext}" if dot else f"{filename}_{counter}"
            target = target_dir / candidate
            counter += 1

    target.write_bytes(content)
    log.info("Monatsordner-Kopie geschrieben: %s", target)
    return target
