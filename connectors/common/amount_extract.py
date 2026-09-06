"""Best-effort Extraktion eines Rechnungsbetrags aus E-Mail-Text.

Zweck: Bestellbestätigungen/Rechnungsmails (Amazon, AliExpress, PayPal, ...)
nennen den Gesamtbetrag meist im Klartext ("Gesamtsumme: 47,98 €",
"Total: $12.99"). Diesen Wert notieren wir zusätzlich zum PDF, damit man in
Docspell später den von OCR erkannten Betrag gegen den aus der Mail bekannten
Betrag abgleichen kann — ein einfacher Plausibilitätscheck gegen OCR-Fehler
bei Zahlen (z.B. vertauschte Ziffern, falsch erkanntes Komma/Punkt).

Das ist bewusst simpel gehalten (Regex, keine Sprachmodell-Extraktion) und
deckt nicht jedes Mail-Layout ab — liefert None, wenn nichts Eindeutiges
gefunden wird, statt zu raten.
"""

from __future__ import annotations

import re

_LABELS = [
    r"gesamtsumme", r"gesamtbetrag", r"gesamt", r"summe", r"rechnungsbetrag",
    r"zu zahlen", r"endbetrag",
    r"total", r"order total", r"grand total", r"amount", r"amount paid",
]
_LABEL_PATTERN = "|".join(_LABELS)

_CURRENCY = r"(EUR|€|USD|\$|CHF|GBP|£)"

# z.B. "Gesamtsumme: 47,98 €"  /  "Total: $12.99"  /  "Betrag 1.234,56 EUR"
_AMOUNT_RE = re.compile(
    rf"(?:{_LABEL_PATTERN})\D{{0,15}}?"
    rf"(?P<currency_pre>{_CURRENCY})?\s*"
    rf"(?P<amount>\d{{1,3}}(?:[.,]\d{{3}})*[.,]\d{{2}})\s*"
    rf"(?P<currency_post>{_CURRENCY})?",
    re.IGNORECASE,
)


def extract_amount(text: str) -> tuple[str, str] | None:
    """Gibt (betrag_normalisiert_als_string, währung) zurück, z.B. ("47.98", "EUR"),
    oder None, wenn nichts Eindeutiges gefunden wurde."""
    match = _AMOUNT_RE.search(text)
    if not match:
        return None

    raw = match.group("amount")
    currency = match.group("currency_pre") or match.group("currency_post") or ""
    currency = _normalize_currency(currency)

    normalized = _normalize_amount(raw)
    if normalized is None:
        return None
    return normalized, currency


def _normalize_amount(raw: str) -> str | None:
    # Heuristik: letztes Komma/Punkt ist der Dezimaltrenner, alles davor
    # sind Tausendertrennzeichen.
    last_comma = raw.rfind(",")
    last_dot = raw.rfind(".")
    decimal_sep_pos = max(last_comma, last_dot)
    if decimal_sep_pos == -1:
        return None
    integer_part = re.sub(r"[.,]", "", raw[:decimal_sep_pos])
    decimal_part = raw[decimal_sep_pos + 1 :]
    if len(decimal_part) != 2:
        return None
    return f"{integer_part}.{decimal_part}"


def _normalize_currency(symbol: str) -> str:
    return {
        "€": "EUR",
        "$": "USD",
        "£": "GBP",
    }.get(symbol, symbol.upper() if symbol else "")


def safe_filename_suffix(text: str) -> str:
    """Für den Dateinamen: '_47.98EUR' oder '' wenn nichts gefunden wurde."""
    result = extract_amount(text)
    if result is None:
        return ""
    amount, currency = result
    return f"_{amount}{currency}"
