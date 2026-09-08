"""Authentifizierter Docspell-Client für LESENDE Operationen (Suche, Download,
Item-Details) — im Gegensatz zu docspell_client.py, der nur den Integration-
Endpoint fürs Hochladen kennt.

Gegen Docspells Scala-Quellcode verifiziert (github.com/docspell/docspell,
Stand siehe ItemSearchPart.scala / AttachmentRoutes.scala / RItem.scala) —
frühere Version dieser Datei war an drei Stellen falsch, seitdem korrigiert:
- Die Suche ist ein GET mit Query-String-Parametern (q/limit/offset), keine
  POST-Anfrage mit JSON-Body.
- "date" kommt als Unix-Millisekunden-Zeitstempel (Integer, kann fehlen,
  wenn Docspell noch kein Datum erkannt hat), nicht als ISO-Datumsstring.
- Der Original-Download läuft über die Attachment-ID
  (/api/v1/sec/attachment/{attachmentId}/original), NICHT über die Item-ID —
  ein Item kann mehrere Attachments haben.
"""

from __future__ import annotations

import dataclasses
import logging
import os
from datetime import datetime, timezone

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
                {"q": query, "limit": page_size, "offset": offset},
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
