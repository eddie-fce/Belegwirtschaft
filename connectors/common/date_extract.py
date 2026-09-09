"""Best-effort Extraktion eines Beleg-/Rechnungsdatums aus per OCR erkanntem
Text — Ergänzung zu Docspells eigener automatischer Datumserkennung, die live
nachweislich unzuverlässig ist (siehe unten), NICHT deren vollständiger
Ersatz.

Hintergrund: Docspells eingebaute Datumserkennung (kein Sprachmodell, ein
einfacher Regex-/Heuristik-Baustein in Docspells Scala-Quellcode:
FindProposal.makeDateProposal + LinkProposal) sammelt ALLE datumsartigen
Zahlenfolgen im Text und nimmt bei mehreren Kandidaten unkommentiert "den
zeitlich nächsten zu heute" — ohne Rücksicht darauf, ob ein Kandidat
überhaupt in der Nähe eines Datums-Labels im Text steht. Bei maschinell
erzeugten Belegen (beobachtet: DHL/Post-Frankierbestätigungen), deren
PDF-Konvertierung offenbar einen zusätzlichen Zeitstempel ins Textlayer
schreibt, führt das nachweislich zu falschen oder gar keinen erkannten
Daten — bestätigt durch einen Live-Vergleich des tatsächlichen OCR-Texts
gegen das (leere) Ergebnis.

Dieser Extractor sucht stattdessen gezielt nach einem Datum in der
unmittelbaren Nähe eines erkennbaren Datums-Labels ("Rechnungsdatum",
"Datum", "Invoice date", ...) — deutlich robuster gegen einzelne
Zeitstempel-Artefakte im Text, auch wenn er (wie amount_extract.py) nicht
jedes Beleg-Layout abdeckt. Liefert None, wenn nichts Eindeutiges gefunden
wird, statt zu raten — das Item landet dann weiterhin im "ohne-datum"-Ordner
zur manuellen Prüfung/Korrektur in Docspell.
"""

from __future__ import annotations

import re
from datetime import date

_LABELS = [
    r"rechnungsdatum", r"belegdatum", r"ausstellungsdatum", r"auftragsdatum",
    r"lieferdatum", r"bestelldatum", r"leistungsdatum",
    r"invoice date", r"date of invoice", r"order date", r"billing date",
    r"datum",  # bewusst zuletzt: am unspezifischsten, hat sonst Vorrang
]
_LABEL_PATTERN = "|".join(_LABELS)

# TT.MM.JJJJ oder TT.MM.JJ, z.B. "23.03.2026" oder "23.03.26"
_DE_DATE = r"(?P<dd>\d{1,2})\.(?P<mm>\d{1,2})\.(?P<yy>\d{2,4})"
# JJJJ-MM-TT, z.B. "2026-03-23"
_ISO_DATE = r"(?P<iso_y>\d{4})-(?P<iso_m>\d{1,2})-(?P<iso_d>\d{1,2})"

_DATE_RE = re.compile(
    rf"(?:{_LABEL_PATTERN})\D{{0,10}}?(?:{_DE_DATE}|{_ISO_DATE})",
    re.IGNORECASE,
)


def extract_date(text: str) -> date | None:
    """Gibt das erste, an ein Datums-Label gebundene Datum im Text zurück,
    oder None, wenn nichts Eindeutiges gefunden wurde."""
    match = _DATE_RE.search(text)
    if not match:
        return None

    if match.group("dd"):
        day, month, year = int(match.group("dd")), int(match.group("mm")), int(match.group("yy"))
        if year < 100:
            year += 2000
    else:
        year, month, day = int(match.group("iso_y")), int(match.group("iso_m")), int(match.group("iso_d"))

    try:
        return date(year, month, day)
    except ValueError:
        return None
