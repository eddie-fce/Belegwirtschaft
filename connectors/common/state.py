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
                    expected_amount TEXT,
                    expected_currency TEXT,
                    PRIMARY KEY (source, external_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS connector_status (
                    source TEXT PRIMARY KEY,
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    last_success_at TEXT,
                    alerted_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mirrored_attachments (
                    attachment_id TEXT PRIMARY KEY,
                    item_id TEXT NOT NULL,
                    mirrored_path TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
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

    def mark_processed(
        self,
        source: str,
        external_id: str,
        expected_amount: str | None = None,
        expected_currency: str | None = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO processed
                    (source, external_id, expected_amount, expected_currency)
                VALUES (?, ?, ?, ?)
                """,
                (source, external_id, expected_amount, expected_currency),
            )

    # --- Fehler-Streak pro Connector, für Alarmierung bei wiederholtem Scheitern ---

    def record_failure(self, source: str) -> int:
        """Erhöht den Fehlzähler für diesen Connector und gibt den neuen Stand zurück."""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO connector_status (source, consecutive_failures)
                VALUES (?, 1)
                ON CONFLICT(source) DO UPDATE SET
                    consecutive_failures = consecutive_failures + 1
                """,
                (source,),
            )
            row = conn.execute(
                "SELECT consecutive_failures FROM connector_status WHERE source = ?",
                (source,),
            ).fetchone()
        return row[0] if row else 1

    def record_success(self, source: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO connector_status (source, consecutive_failures, last_success_at)
                VALUES (?, 0, datetime('now'))
                ON CONFLICT(source) DO UPDATE SET
                    consecutive_failures = 0,
                    last_success_at = datetime('now'),
                    alerted_at = NULL
                """,
                (source,),
            )

    def should_alert(self, source: str, threshold: int) -> bool:
        """True, wenn der Fehlzähler die Schwelle erreicht/überschritten hat und für
        diesen Fehler-Streak noch nicht alarmiert wurde (verhindert Spam bei jedem
        weiteren Fehlschlag)."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT consecutive_failures, alerted_at FROM connector_status WHERE source = ?",
                (source,),
            ).fetchone()
            if not row:
                return False
            failures, alerted_at = row
            if failures >= threshold and alerted_at is None:
                conn.execute(
                    "UPDATE connector_status SET alerted_at = datetime('now') WHERE source = ?",
                    (source,),
                )
                return True
        return False

    # --- Mirror-Sync: welche Docspell-Attachments liegen aktuell wo im
    # Jahr/Monat-Ordnerbaum? Ermöglicht, eine Datei zu verschieben statt zu
    # duplizieren, wenn sich das erkannte Beleg-Datum ändert, und verwaiste
    # Kopien zu entfernen, wenn ein Item in Docspell gelöscht wird.

    def get_mirrored_path(self, attachment_id: str) -> str | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT mirrored_path FROM mirrored_attachments WHERE attachment_id = ?",
                (attachment_id,),
            ).fetchone()
        return row[0] if row else None

    def set_mirrored_path(self, attachment_id: str, item_id: str, path: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO mirrored_attachments (attachment_id, item_id, mirrored_path, updated_at)
                VALUES (?, ?, ?, datetime('now'))
                ON CONFLICT(attachment_id) DO UPDATE SET
                    mirrored_path = excluded.mirrored_path,
                    updated_at = datetime('now')
                """,
                (attachment_id, item_id, path),
            )

    def all_mirrored_attachment_ids(self) -> set[str]:
        with self._conn() as conn:
            rows = conn.execute("SELECT attachment_id FROM mirrored_attachments").fetchall()
        return {r[0] for r in rows}

    def remove_mirrored(self, attachment_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM mirrored_attachments WHERE attachment_id = ?", (attachment_id,)
            )
