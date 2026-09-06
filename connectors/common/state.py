"""Sehr einfache, dateibasierte Dedupe-Ablage für die Connectors.

Verhindert, dass dieselbe E-Mail / dieselbe Amazon-Rechnung bei jedem Poll-Zyklus
erneut hochgeladen wird. Liegt als SQLite-Datei im gemeinsamen /state-Volume —
bleibt lokal, verlässt den Rechner nie.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path


class ProcessedStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS processed (
                    source TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    processed_at TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (source, external_id)
                )
                """
            )

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def is_processed(self, source: str, external_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM processed WHERE source = ? AND external_id = ?",
                (source, external_id),
            ).fetchone()
        return row is not None

    def mark_processed(self, source: str, external_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO processed (source, external_id) VALUES (?, ?)",
                (source, external_id),
            )
