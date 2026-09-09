#!/usr/bin/env bash
# Verschlüsseltes Backup von Datenbank + Belegen via restic (https://restic.net).
# Verschlüsselung passiert lokal, VOR dem Verlassen dieses Rechners — das
# Backup-Ziel (externe Platte, NAS, auch ein Cloud-Bucket) sieht nur
# Chiffretext, muss also nicht vertrauenswürdig sein.
#
# Läuft containerisiert (Service "backup" in docker-compose.yml, Dockerfile
# scripts/Dockerfile.backup) — restic ist auf dieser NAS nicht ohne Weiteres
# nativ installierbar, genau wie Python bei den Connectors. Läuft im selben
# Docker-Netz wie "db" (direkte Postgres-Verbindung, kein
# "docker compose exec" nötig, das würde einen Docker-Socket im Container
# voraussetzen).
#
# Einrichtung als tägliche Aufgabe (nicht automatisch eingerichtet — bewusst,
# da Cron-Änderungen am System hier nicht selbständig vorgenommen werden
# sollen):
#   crontab -e
#   0 3 * * * cd /pfad/zu/belegwirtschaft && docker compose run --rm backup >> data/backup.log 2>&1

set -euo pipefail
cd "$(dirname "$0")/.."

if [ -z "${RESTIC_REPOSITORY:-}" ] || [ -z "${RESTIC_PASSWORD:-}" ]; then
  echo "RESTIC_REPOSITORY/RESTIC_PASSWORD nicht gesetzt (.env) — Backup übersprungen." >&2
  exit 1
fi

if ! restic snapshots >/dev/null 2>&1; then
  echo "-> Repository existiert noch nicht, initialisiere..."
  restic init
fi

# Konsistenter DB-Dump statt einfach die laufenden Postgres-Datendateien zu
# kopieren (die könnten mitten in einer Schreiboperation erwischt werden).
# Direkte Verbindung über den Docker-Servicenamen "db" (selbes "internal"-
# Netz), kein "docker compose exec" nötig.
echo "-> Erzeuge Datenbank-Dump..."
PGPASSWORD="${POSTGRES_PASSWORD}" pg_dump -h db -U "${POSTGRES_USER}" "${POSTGRES_DB}" > /data/db_dump.sql

echo "-> Sichere ./data (Belege, DB-Dump, Sessions, Connector-State)..."
restic backup /data \
  --exclude /data/db \
  --tag belegwirtschaft

echo "-> Alte Backups aufräumen (7 täglich, 4 wöchentlich, 12 monatlich)..."
restic forget --keep-daily 7 --keep-weekly 4 --keep-monthly 12 --prune

echo "-> Fertig. Snapshot-Liste:"
restic snapshots --tag belegwirtschaft
