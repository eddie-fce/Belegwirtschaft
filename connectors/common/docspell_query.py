"""Authentifizierter Docspell-Client für LESENDE Operationen (Suche, Download,
Item-Details) — im Gegensatz zu docspell_client.py, der nur den Integration-
Endpoint fürs Hochladen kennt.

ACHTUNG — Best-Effort / ungetestet gegen Live-Docspell:
Der Netzwerkzugriff auf docspell.org war beim Erstellen dieses Codes technisch
blockiert (siehe README), daher basiert die Session-Login-/Such-API unten auf
dem allgemein bekannten Docspell-REST-Schema (Login gegen
/api/v1/open/auth/login, danach Requests mit dem zurückgegebenen Auth-Token),
ist aber NICHT gegen eine laufende Docspell-Instanz verifiziert. Vor
produktivem Einsatz bitte gegen die aktuelle API-Referenz
(https://docspell.org/openapi/) prüfen und die mit "ADJUST" markierten Stellen
bei Bedarf anpassen. Nutzung ist bewusst defensiv (klare Fehlermeldungen statt
stillem Falsch-Verhalten), damit ein API-Mismatch schnell auffällt.
"""

from __future__ import annotations

import dataclasses
import logging
import os

import requests

log = logging.getLogger(__name__)


class DocspellAuthError(RuntimeError):
    pass


@dataclasses.dataclass
class SearchResult:
    item_id: str
    name: str
    correspondent: str | None
    date: str | None
    tags: list[str]


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
        # ADJUST: Pfad/Feldnamen gegen https://docspell.org/openapi/ prüfen.
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
        token = data.get("token")
        if not token:
            raise DocspellAuthError(f"Login-Antwort enthielt kein Token: {data}")
        self._token = token
        return token

    def _headers(self) -> dict:
        if not self._token:
            self._login()
        # ADJUST: Header-Name gegen aktuelle Docspell-Version prüfen (in älteren
        # Versionen "X-Docspell-Auth").
        return {"X-Docspell-Auth": self._token}

    def search(self, query: str, limit: int = 200) -> list[SearchResult]:
        """query ist Docspells eigene Such-DSL, z.B. 'tag:Rechnung date>=2026-01-01'."""
        resp = self.session.post(
            f"{self.base_url}/api/v1/sec/item/search",
            headers=self._headers(),
            json={"query": query, "limit": limit},
            timeout=60,
        )
        if resp.status_code == 401:
            self._token = None
            resp = self.session.post(
                f"{self.base_url}/api/v1/sec/item/search",
                headers=self._headers(),
                json={"query": query, "limit": limit},
                timeout=60,
            )
        if resp.status_code != 200:
            raise RuntimeError(f"Docspell-Suche fehlgeschlagen ({resp.status_code}): {resp.text[:300]}")

        items = resp.json().get("groups", [])
        results = []
        for group in items:
            for item in group.get("items", []):
                results.append(
                    SearchResult(
                        item_id=item["id"],
                        name=item.get("name", ""),
                        correspondent=(item.get("corrOrg") or {}).get("name"),
                        date=item.get("date"),
                        tags=[t.get("name") for t in item.get("tags", [])],
                    )
                )
        return results

    def download_original(self, item_id: str) -> bytes:
        # ADJUST: Attachment-Enumeration ausgelassen — nimmt hier vereinfachend an,
        # dass genau ein Original-Attachment pro Item existiert (Normalfall für per
        # Connector hochgeladene Einzel-PDFs). Bei Multi-Attachment-Items ggf.
        # zuerst /api/v1/sec/item/{id} abfragen und über die Attachment-IDs iterieren.
        resp = self.session.get(
            f"{self.base_url}/api/v1/sec/attachment/{item_id}/original",
            headers=self._headers(),
            timeout=60,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Download für Item {item_id} fehlgeschlagen ({resp.status_code})"
            )
        return resp.content
