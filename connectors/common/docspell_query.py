"""Authentifizierter Docspell-Client für LESENDE Operationen (Suche, Download,
Item-Details) — im Gegensatz zu docspell_client.py, der nur den Integration-
Endpoint fürs Hochladen kennt.

Gegen Docspells Scala-Quellcode verifiziert (github.com/docspell/docspell,
Stand siehe ItemSearchPart.scala / AttachmentRoutes.scala / RItem.scala) —
frühere Version dieser Datei war an vier Stellen falsch, seitdem korrigiert
(die letzte davon erst live gegen eine laufende Instanz aufgefallen):
- Die Suche ist ein GET mit Query-String-Parametern (q/limit/offset), keine
  POST-Anfrage mit JSON-Body.
- "date" kommt als Unix-Millisekunden-Zeitstempel (Integer, kann fehlen,
  wenn Docspell noch kein Datum erkannt hat), nicht als ISO-Datumsstring.
- Der Original-Download läuft über die Attachment-ID
  (/api/v1/sec/attachment/{attachmentId}/original), NICHT über die Item-ID —
  ein Item kann mehrere Attachments haben.
- Ohne den Query-Parameter "withDetails=true" liefert die Suche für jedes
  Item eine leere "attachments"-Liste zurück, selbst wenn welche existieren.
- Das "date"-Feld der Suche/Listenansicht ist serverseitig
  coalesce(itemDate, created) (siehe QItem.scala) — ein Item ganz ohne von
  Docspell erkanntes Datum liefert dort trotzdem einen Wert (das Upload-/
  Verarbeitungsdatum), nicht unterscheidbar von einem echten Treffer. Wer
  das echte, tatsächlich nullable Datum braucht (z.B. für die Monatsordner-
  Sortierung), muss get_item_date() nutzen (Item-Detailsicht,
  GET /api/v1/sec/item/{id}, Feld "itemDate").
"""

from __future__ import annotations

import dataclasses
import logging
import os
from datetime import date, datetime, timezone

import requests

log = logging.getLogger(__name__)


class DocspellAuthError(RuntimeError):
    pass


@dataclasses.dataclass
class Attachment:
    id: str
    name: str | None


@dataclasses.dataclass
class SearchResult:
    item_id: str
    name: str
    correspondent: str | None
    date: datetime | None
    tags: list[str]
    attachments: list[Attachment]


class DocspellQueryClient:
    def __init__(
        self,
        base_url: str | None = None,
        account: str | None = None,
        password: str | None = None,
    ) -> None:
        self.base_url = (base_url or os.environ["DOCSPELL_BASE_URL"]).rstrip("/")
        self.account = account or os.environ["DOCSPELL_ACCOUNT"]  # z.B. "firma/edwin"
        self.password = password or os.environ["DOCSPELL_PASSWORD"]
        self._token: str | None = None
        self.session = requests.Session()

    def _login(self) -> str:
        resp = self.session.post(
            f"{self.base_url}/api/v1/open/auth/login",
            json={"account": self.account, "password": self.password},
            timeout=30,
        )
        if resp.status_code != 200:
            raise DocspellAuthError(
                f"Docspell-Login fehlgeschlagen ({resp.status_code}): {resp.text[:300]}"
            )
        data = resp.json()
        if not data.get("success") or not data.get("token"):
            raise DocspellAuthError(f"Docspell-Login abgelehnt: {data.get('message', data)}")
        self._token = data["token"]
        return self._token

    def _headers(self) -> dict:
        if not self._token:
            self._login()
        return {"X-Docspell-Auth": self._token}

    def _get(self, path: str, params: dict) -> requests.Response:
        resp = self.session.get(
            f"{self.base_url}{path}", headers=self._headers(), params=params, timeout=60
        )
        if resp.status_code == 401:
            # Token abgelaufen — einmal neu einloggen und erneut versuchen.
            self._token = None
            resp = self.session.get(
                f"{self.base_url}{path}", headers=self._headers(), params=params, timeout=60
            )
        return resp

    def search(self, query: str, page_size: int = 200) -> list[SearchResult]:
        """query ist Docspells eigene Such-DSL, leerer String = alle (nicht im
        Papierkorb befindlichen) Items der Collective. Paginiert automatisch
        über alle Treffer, unabhängig davon, wie viele es sind."""
        results: list[SearchResult] = []
        offset = 0
        while True:
            resp = self._get(
                "/api/v1/sec/item/search",
                # withDetails=true ist nötig, damit Docspell die Attachment-
                # Liste je Item überhaupt mitliefert — ohne das kommt
                # "attachments": [] zurück, selbst wenn das Item welche hat
                # (gegen Live-Instanz verifiziert: ItemSearchPart.scala,
                # OSearch.searchSelect(details, ...)).
                {"q": query, "limit": page_size, "offset": offset, "withDetails": "true"},
            )
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Docspell-Suche fehlgeschlagen ({resp.status_code}): {resp.text[:300]}"
                )
            body = resp.json()
            page_items: list[SearchResult] = []
            for group in body.get("groups", []):
                for item in group.get("items", []):
                    page_items.append(
                        SearchResult(
                            item_id=item["id"],
                            name=item.get("name", ""),
                            correspondent=(item.get("corrOrg") or {}).get("name"),
                            date=_parse_epoch_ms(item.get("date")),
                            tags=[t.get("name") for t in item.get("tags", [])],
                            attachments=[
                                Attachment(id=a["id"], name=a.get("name"))
                                for a in item.get("attachments", [])
                            ],
                        )
                    )
            results.extend(page_items)
            if len(page_items) < page_size:
                break
            offset += page_size
        return results

    def get_item_date(self, item_id: str) -> datetime | None:
        """Das ECHTE, von Docspell erkannte (oder in der Oberfläche manuell
        gesetzte) Beleg-Datum — im Unterschied zum "date"-Feld der Such-/
        Listenansicht (search()): das liefert serverseitig IMMER einen Wert
        zurück, auch wenn nie eines erkannt wurde (Postgres-Query verwendet
        coalesce(itemDate, created), siehe QItem.scala) — dann eben das
        Upload-/Verarbeitungsdatum, von aussen nicht unterscheidbar von einem
        echten Treffer. Die Item-Detailsicht dagegen liefert das rohe,
        tatsächlich nullable "itemDate"-Feld. Für die Monatsordner-Sortierung
        muss deshalb dieser Weg genutzt werden, nicht SearchResult.date."""
        resp = self._get(f"/api/v1/sec/item/{item_id}", {})
        if resp.status_code != 200:
            raise RuntimeError(
                f"Item-Detail für {item_id} fehlgeschlagen ({resp.status_code}): {resp.text[:300]}"
            )
        return _parse_epoch_ms(resp.json().get("itemDate"))

    def get_extracted_text(self, attachment_id: str) -> str:
        """Der von Docspell per OCR erkannte Text eines Attachments — Basis
        für den eigenen Datums-Fallback (siehe common/date_extract.py), wenn
        Docspells eigene Erkennung nichts liefert."""
        resp = self._get(f"/api/v1/sec/attachment/{attachment_id}/extracted-text", {})
        if resp.status_code != 200:
            raise RuntimeError(
                f"Extrahierter Text für Attachment {attachment_id} fehlgeschlagen "
                f"({resp.status_code}): {resp.text[:300]}"
            )
        return resp.json().get("text") or ""

    def set_item_date(self, item_id: str, when: date) -> None:
        """Schreibt ein Datum als Docspells eigenes itemDate zurück (PUT
        .../item/{id}/date, Body {"date": <epoch-ms>}) — genutzt, wenn unser
        eigener Datums-Fallback (date_extract.py) etwas findet, das
        Docspells eigene Erkennung übersehen hat. Damit ist die Korrektur
        auch in Docspells Oberfläche sichtbar und muss beim nächsten
        Sync-Lauf nicht erneut extrahiert werden."""
        midnight_utc = datetime(when.year, when.month, when.day, tzinfo=timezone.utc)
        epoch_ms = int(midnight_utc.timestamp() * 1000)
        resp = self.session.put(
            f"{self.base_url}/api/v1/sec/item/{item_id}/date",
            headers=self._headers(),
            json={"date": epoch_ms},
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Datum setzen für Item {item_id} fehlgeschlagen ({resp.status_code}): {resp.text[:300]}"
            )

    def download_original(self, attachment_id: str) -> bytes:
        resp = self.session.get(
            f"{self.base_url}/api/v1/sec/attachment/{attachment_id}/original",
            headers=self._headers(),
            timeout=60,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Download für Attachment {attachment_id} fehlgeschlagen ({resp.status_code})"
            )
        return resp.content


def _parse_epoch_ms(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (TypeError, ValueError):
        return None
