"""Minimaler Client für Docspells "Integration Endpoint".

Der Integration-Endpoint erlaubt es, Dateien ohne Benutzer-Login direkt in eine
Docspell-Collective hochzuladen — geschützt durch ein gemeinsames Secret
(DOCSPELL_INTEGRATION_SECRET), das Server und Connectors gleichermassen kennen.
Genau dafür ist er gedacht (automatisierte Zulieferung von Belegen), im Gegensatz
zur normalen Login-API, die für interaktive Nutzer gedacht ist.

Referenz: https://docspell.org/docs/api/upload/ — Abschnitt "Integration Endpoint".
Vor dem ersten produktiven Einsatz gegen die aktuelle Doku prüfen (in dieser Sandbox
war docspell.org netzwerkseitig nicht erreichbar).
"""

from __future__ import annotations

import dataclasses
import logging
import os
from typing import Iterable

import requests

log = logging.getLogger(__name__)


@dataclasses.dataclass
class DocspellMeta:
    """Metadaten, die zusammen mit einer Datei übergeben werden."""

    correspondent: str | None = None
    tags: list[str] = dataclasses.field(default_factory=list)
    folder: str | None = None
    # "incoming" (Eingang, Default) oder "outgoing" (Ausgang) — Docspells
    # eigenes Direction-Feld. Bisher immer fest auf "incoming" gesetzt, auch
    # bei Ausgangsrechnungen (die Eingang/Ausgang-Unterscheidung lief bislang
    # nur über die gleichnamigen Tags, siehe common/monthly_mirror.py).
    direction: str = "incoming"


class DocspellClient:
    def __init__(
        self,
        base_url: str | None = None,
        collective: str | None = None,
        secret: str | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = (base_url or os.environ["DOCSPELL_BASE_URL"]).rstrip("/")
        self.collective = collective or os.environ["DOCSPELL_COLLECTIVE"]
        self.secret = secret or os.environ["DOCSPELL_INTEGRATION_SECRET"]
        self.session = session or requests.Session()

    def _upload_url(self) -> str:
        return f"{self.base_url}/api/v1/open/integration/item/{self.collective}"

    def upload(self, filename: str, content: bytes, meta: DocspellMeta | None = None) -> bool:
        """Lädt eine einzelne Datei hoch. Gibt True bei Erfolg zurück.

        Docspell dedupliziert serverseitig bereits per Datei-Hash — ein erneuter
        Upload derselben Datei landet nicht doppelt in der Ablage. Für den
        Connector-eigenen "haben wir das schon verarbeitet"-Check siehe state.py.
        """
        meta = meta or DocspellMeta()
        meta_json = {
            "multiple": False,
            "direction": meta.direction,
        }
        if meta.folder:
            meta_json["folder"] = meta.folder
        if meta.tags:
            # Docspells "StringList"-Schema erwartet ein Objekt {"items": [...]},
            # keine nackte Liste (siehe ItemUploadMeta/StringList im OpenAPI-Schema).
            meta_json["tags"] = {"items": meta.tags}

        files = {"file": (filename, content)}
        data = {"meta": _to_json(meta_json)}
        headers = {"Docspell-Integration-Secret": self.secret}

        resp = self.session.post(
            self._upload_url(), headers=headers, files=files, data=data, timeout=60
        )
        if resp.status_code >= 300:
            log.error("Docspell-Upload fehlgeschlagen (%s): %s", resp.status_code, resp.text[:500])
            return False
        log.info("Hochgeladen: %s", filename)
        return True

    def upload_many(self, items: Iterable[tuple[str, bytes, DocspellMeta]]) -> int:
        ok = 0
        for filename, content, meta in items:
            if self.upload(filename, content, meta):
                ok += 1
        return ok


def _to_json(obj: dict) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)
