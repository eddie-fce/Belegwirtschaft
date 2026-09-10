"""Mirror-Sync: baut den durchsuchbaren Jahr/Monat-Ordnerbaum unter
./data/belege-nach-monat NICHT mehr aus einer Datums-Näherung der Connectors
beim Upload, sondern direkt aus Docspells eigenem, von der OCR erkannten
(oder in der Docspell-Oberfläche manuell korrigierten) Beleg-Datum. Das ist
das tatsächliche Rechnungs-/Kaufdatum, nicht das E-Mail-Eingangsdatum oder
die Datei-mtime eines Handyfotos — wichtig, weil der Steuerberater direkt auf
diesen Ordnerbaum zugreift und sich auf die richtige Periode verlassen muss.

Läuft periodisch gegen die normale (Nutzer-)Login-API, nicht den Integration-
Endpoint, weil dafür Suche + Originaldatei-Download nötig sind (siehe
common/docspell_query.py). Erfasst dabei ALLE Items der Collective, nicht nur
per Connector hochgeladene — auch manuell in Docspells Oberfläche eingefügte
Belege landen so automatisch im Ordnerbaum (das war vorher eine bekannte
Lücke, siehe README-Abschnitt "Nutzung im Alltag").

WICHTIG (live aufgefallen): das Datum aus der normalen Suche ist serverseitig
coalesce(itemDate, created) — Items ganz ohne von Docspell erkanntes Datum
liefern dort trotzdem einen Wert (das Upload-/Verarbeitungsdatum), nicht
unterscheidbar von einem echten Treffer. Deshalb holt dieses Skript das
tatsächliche, nullable Datum separat je Item über die Detailsicht
(client.get_item_detail, siehe docspell_query.py) statt sich auf das
Suchergebnis zu verlassen.

Verhalten je Sync-Lauf:
- Attachment mit von Docspell erkanntem Datum -> Datei liegt/landet unter
  <Jahr>/<Eingang|Ausgang>/<Monat>/dateiname.
- Attachment (noch) ohne erkanntes Datum -> ohne-datum/<Eingang|Ausgang>/
  dateiname. Kein Rateversuch mit dem heutigen Datum — das würde einen alten
  Beleg im falschen Monat einsortieren. Sobald Docspell später ein Datum
  erkennt oder es manuell in der Oberfläche gesetzt wird, verschiebt der
  nächste Lauf die Datei automatisch an die richtige Stelle.
- Eingang/Ausgang wird an den vom Gmail-/Dropzone-Connector gesetzten Tags
  festgemacht, NICHT an Docspells eigenem "direction"-Feld — das setzt der
  Integration-Endpoint-Client aktuell immer fest auf "incoming"
  (siehe common/docspell_client.py, unabhängiger, für sich zu behebender
  Punkt).
- Ändert sich das erkannte Datum eines bereits gespiegelten Attachments
  (Nach-OCR oder manuelle Korrektur), wird die alte Kopie entfernt und unter
  dem neuen Pfad neu geschrieben — keine Duplikate.
- Wird ein Item in Docspell gelöscht (Papierkorb), verschwindet die
  gespiegelte Datei beim nächsten Lauf automatisch wieder.

Mögliche Duplikate (z.B. eine Rechnung, die einmal per Mail und einmal
manuell erneut hochgeladen wurde — Docspells eigene Deduplizierung
erkennt das nicht, die läuft nur über exakte Datei-Hashes, hier sind es aber
zwei unterschiedliche Dateien mit demselben Inhalt): Items mit gleichem
erkannten Beleg-Datum UND gleichem aus dem Text erkannten Betrag (siehe
common/amount_extract.py) gelten als wahrscheinliches Duplikat. Nichts wird
gelöscht — von jeder Gruppe bleibt nur das älteste Item (kleinste Docspell-
ID) am normalen Platz, alle anderen landen zur manuellen Prüfung unter
<Jahr>/Duplikate/<Eingang|Ausgang>/. Ohne erkannten Betrag (z.B. schlechte
OCR-Qualität) wird ein Item nie als Duplikat markiert — lieber ein
übersehenes Duplikat als ein fälschlich aussortierter echter Beleg.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

# Im Docker-Image liegt "common/" direkt neben dieser Datei (vom Dockerfile so
# kopiert); in einem rohen Git-Checkout liegt es stattdessen eine Ebene höher
# unter connectors/common. Beide Fälle abdecken.
_here = Path(__file__).resolve().parent
for _candidate in (_here, _here.parent):
    if (_candidate / "common").is_dir():
        sys.path.insert(0, str(_candidate))
        break

from common.amount_extract import extract_amount  # noqa: E402
from common.date_extract import extract_date  # noqa: E402
from common.docspell_query import DocspellQueryClient, ItemDetailInfo, SearchResult  # noqa: E402
from common.monthly_mirror import mirror as mirror_to_month_folder  # noqa: E402
from common.monthly_mirror import remove as remove_mirrored  # noqa: E402
from common.notify import notify  # noqa: E402
from common.state import ProcessedStore  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("mirror-sync")

STATE_DB = Path("/state/mirror-sync.sqlite3")
MONTHLY_MIRROR_DIR = Path("/monthly")


@dataclasses.dataclass
class _ItemInfo:
    item: SearchResult
    kind: str
    real_date: date | None
    detail: ItemDetailInfo
    amount_key: tuple[str, str] | None  # (betrag, währung) aus dem OCR-Text, falls erkannt


def _kind(tags: list[str]) -> str:
    return "Ausgang" if "Ausgang" in tags else "Eingang"


def _target_path(
    item_name: str,
    att_name: str | None,
    when: date | None,
    kind: str,
    is_duplicate: bool = False,
) -> Path:
    filename = att_name or item_name or "beleg.pdf"
    if is_duplicate:
        year = f"{when:%Y}" if when is not None else "ohne-datum"
        return MONTHLY_MIRROR_DIR / year / "Duplikate" / kind / filename
    if when is not None:
        return MONTHLY_MIRROR_DIR / f"{when:%Y}" / kind / f"{when:%m}" / filename
    return MONTHLY_MIRROR_DIR / "ohne-datum" / kind / filename


def _load_item_infos(client: DocspellQueryClient, results: list[SearchResult]) -> list[_ItemInfo]:
    infos = []
    for item in results:
        kind = _kind(item.tags)
        # WICHTIG: item.date aus der Suche ist serverseitig
        # coalesce(itemDate, created) — liefert also auch dann einen Wert,
        # wenn Docspell nie ein echtes Datum erkannt hat (dann eben das
        # Upload-Datum, nicht unterscheidbar von einem echten Treffer). Das
        # tatsächliche, nullable Datum gibt es nur über die Item-
        # Detailsicht (siehe docspell_query.py).
        try:
            detail = client.get_item_detail(item.item_id)
            real_date = detail.item_date
        except Exception:
            log.exception("Konnte Item-Detail für %s (%s) nicht laden", item.item_id, item.name)
            continue

        # Einmal den OCR-Text laden — Basis sowohl für den Datums-Fallback
        # als auch für die Duplikat-Erkennung über den erkannten Betrag.
        text = None
        if item.attachments:
            try:
                text = client.get_extracted_text(item.attachments[0].id)
            except Exception:
                log.debug("Konnte OCR-Text für Item %s (%s) nicht laden", item.item_id, item.name)

        # Fallback, falls Docspell selbst kein Datum erkannt hat: live
        # bestätigt unzuverlässig bei maschinell erzeugten Belegen (siehe
        # date_extract.py) — eigene, Label-gebundene Suche im OCR-Text
        # probieren, bevor das Item im "ohne-datum"-Ordner landet. Bei
        # Erfolg wird das Datum zusätzlich in Docspell zurückgeschrieben,
        # damit es auch dort korrekt sichtbar ist und beim nächsten Lauf
        # nicht erneut extrahiert werden muss.
        if real_date is None and text:
            found = extract_date(text)
            if found is not None:
                try:
                    client.set_item_date(item.item_id, found)
                    real_date = found
                    log.info("Datum selbst erkannt und in Docspell gesetzt: %s -> %s", item.name, found)
                except Exception:
                    log.exception(
                        "Konnte selbst erkanntes Datum nicht in Docspell setzen für Item %s (%s)",
                        item.item_id,
                        item.name,
                    )

        amount_key = extract_amount(text) if text else None
        infos.append(_ItemInfo(item=item, kind=kind, real_date=real_date, detail=detail, amount_key=amount_key))
    return infos


def _find_duplicate_ids(infos: list[_ItemInfo]) -> set[str]:
    """Gruppiert Items mit gleichem Datum + gleichem erkanntem Betrag.
    Aus jeder Gruppe von 2+ bleibt nur das älteste Item (kleinste Docspell-
    ID — Docspells IDs sind zeitlich sortierbare ULID-artige Strings) am
    normalen Platz, der Rest gilt als Duplikat."""
    groups: dict[tuple[date, str, str], list[str]] = defaultdict(list)
    for info in infos:
        if info.real_date is not None and info.amount_key is not None:
            key = (info.real_date.date() if hasattr(info.real_date, "date") else info.real_date, *info.amount_key)
            groups[key].append(info.item.item_id)

    duplicate_ids: set[str] = set()
    for ids in groups.values():
        if len(ids) > 1:
            primary = min(ids)
            duplicate_ids.update(i for i in ids if i != primary)
    return duplicate_ids


def run_once(client: DocspellQueryClient, store: ProcessedStore) -> None:
    results = client.search("")
    infos = _load_item_infos(client, results)
    duplicate_ids = _find_duplicate_ids(infos)

    seen_attachment_ids: set[str] = set()
    new_count = moved_count = unchanged_count = failed_count = 0

    for info in infos:
        item, kind, real_date, detail = info.item, info.kind, info.real_date, info.detail
        is_duplicate = item.item_id in duplicate_ids

        for att in item.attachments:
            seen_attachment_ids.add(att.id)
            # Echter Original-Dateiname statt des von Docspells interner
            # PDF-Normalisierung umbenannten Attachment-Namens (".converted"),
            # falls vorhanden.
            att_name = detail.source_names.get(att.id, att.name)
            desired_path = _target_path(item.name, att_name, real_date, kind, is_duplicate)
            previous_path_str = store.get_mirrored_path(att.id)

            if previous_path_str == str(desired_path) and desired_path.exists():
                unchanged_count += 1
                continue

            try:
                content = client.download_original(att.id)
            except Exception:
                log.exception(
                    "Download fehlgeschlagen für Attachment %s (Item %s, %s)",
                    att.id,
                    item.item_id,
                    item.name,
                )
                failed_count += 1
                continue

            mirror_to_month_folder(
                MONTHLY_MIRROR_DIR, desired_path.name, content, when=real_date, kind=kind
            )

            if previous_path_str and previous_path_str != str(desired_path):
                remove_mirrored(Path(previous_path_str))
                moved_count += 1
            else:
                new_count += 1

            store.set_mirrored_path(att.id, item.item_id, str(desired_path))

    stale_ids = store.all_mirrored_attachment_ids() - seen_attachment_ids
    for att_id in stale_ids:
        path_str = store.get_mirrored_path(att_id)
        if path_str:
            remove_mirrored(Path(path_str))
        store.remove_mirrored(att_id)

    log.info(
        "Sync fertig: %d neu, %d verschoben (Datum geändert), %d unverändert, "
        "%d entfernt (in Docspell gelöscht), %d Downloads fehlgeschlagen, "
        "%d mögliche Duplikate",
        new_count,
        moved_count,
        unchanged_count,
        len(stale_ids),
        failed_count,
        len(duplicate_ids),
    )


def main() -> None:
    client = DocspellQueryClient()
    store = ProcessedStore(STATE_DB)
    interval = int(os.environ.get("MIRROR_SYNC_POLL_INTERVAL_SECONDS", "1800"))
    alert_threshold = int(os.environ.get("MIRROR_SYNC_ALERT_AFTER_FAILURES", "3"))

    while True:
        try:
            run_once(client, store)
            store.record_success("mirror-sync")
        except Exception as exc:
            log.exception("Fehler im Mirror-Sync-Durchlauf")
            failures = store.record_failure("mirror-sync")
            if store.should_alert("mirror-sync", alert_threshold):
                notify(
                    "Belegwirtschaft: Mirror-Sync gestört",
                    f"{failures} Durchläufe in Folge fehlgeschlagen. Letzter Fehler: {exc}\n"
                    "Bitte Logs prüfen: docker compose logs connector-mirror-sync",
                    priority="high",
                )
        time.sleep(interval)


if __name__ == "__main__":
    main()
