#!/usr/bin/env bash
# Einmaliges Setup: legt lokale Verzeichnisse an und erzeugt .env, falls nicht vorhanden.
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p data/db data/solr data/docspell-files data/state data/dropzone
mkdir -p connectors/gmail/secrets connectors/amazon/secrets connectors/amazon-business/secrets

if [ ! -f .env ]; then
  cp .env.example .env
  # Zufällige Secrets erzeugen statt der Platzhalter
  if command -v openssl >/dev/null; then
    sed -i.bak "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(openssl rand -hex 24)/" .env
    sed -i.bak "s/^DOCSPELL_INTEGRATION_SECRET=.*/DOCSPELL_INTEGRATION_SECRET=$(openssl rand -hex 32)/" .env
    sed -i.bak "s/^RESTIC_PASSWORD=.*/RESTIC_PASSWORD=$(openssl rand -hex 32)/" .env
    rm -f .env.bak
  fi
  echo "-> .env erzeugt. Bitte kurz durchsehen (Collective-Name, DOCSPELL_VERSION, RESTIC_REPOSITORY etc.)."
else
  echo "-> .env existiert bereits, wird nicht verändert."
fi

echo ""
echo "Fertig. Nächste Schritte:"
echo "  1. connectors/gmail/README.md folgen (Gmail-Login einmalig lokal)"
echo "  2. connectors/amazon/README.md folgen (Amazon-Login einmalig lokal)"
echo "  3. docker compose up -d"
echo "  4. http://localhost:7880 öffnen und Docspell-Account anlegen"
