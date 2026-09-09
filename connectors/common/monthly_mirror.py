"""Schreibt/entfernt Dateien in einem echten, per File Station durchsuchbaren
Ordnerbaum — für den Steuerberater, der eine gewohnte Ordnerstruktur statt
eines Docspell-Logins erwartet.

Struktur: <Jahr>/<Eingang|Ausgang>/<Monat>/datei.pdf — "Eingang" für Belege,
die die Firma empfangen hat (Einkäufe/Rechnungen von Lieferanten), "Ausgang"
für Rechnungen, die die Firma selbst an ihre Kunden stellt. Items, für die
Docspell (noch) kein Datum erkannt hat, landen in ohne-datum/<Eingang|Ausgang>/
statt geraten zu werden — siehe connectors/mirror-sync/mirror_sync.py, das
diese Bausteine periodisch aufruft und dabei automatisch verschiebt, sobald
sich das erkannte Datum ändert (z.B. nachträgliche OCR oder eine manuelle
Korrektur in Docspells Oberfläche).

Läuft parallel zu Docspell, nicht als Ersatz: Docspell bleibt die
durchsuchbare/getaggte Ablage, dieser Ordnerbaum ist eine reine
Sichtbarkeits-Kopie fürs Dateisystem.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

Kind = Literal["Eingang", "Ausgang"]


def mirror(
    base_dir: Path,
    filename: str,
    content: bytes,
    when: date | None,
    kind: Kind = "Eingang",
) -> Path:
    """Schreibt `content` unter base_dir/<Jahr>/<Eingang|Ausgang>/<Monat>/<filename>,
    oder unter base_dir/ohne-datum/<Eingang|Ausgang>/<filename>, falls `when`
    None ist (bewusst kein Fallback auf "heute" — das würde einen alten Beleg
    im falschen Monat einsortieren). Bei einem Namenskonflikt (z.B. zwei
    Belege mit identischem Dateinamen im selben Monat) wird ein Zähler an den
    Dateinamen angehängt, statt zu überschreiben."""
    if when is not None:
        target_dir = base_dir / f"{when:%Y}" / kind / f"{when:%m}"
    else:
        target_dir = base_dir / "ohne-datum" / kind
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


def remove(path: Path) -> None:
    """Entfernt eine zuvor gespiegelte Datei wieder — z.B. weil sich das
    erkannte Beleg-Datum geändert hat (Datei liegt jetzt anderswo) oder das
    zugehörige Docspell-Item gelöscht/in den Papierkorb verschoben wurde."""
    try:
        path.unlink(missing_ok=True)
        log.info("Monatsordner-Kopie entfernt: %s", path)
    except OSError:
        log.warning("Konnte gespiegelte Datei nicht entfernen: %s", path)
