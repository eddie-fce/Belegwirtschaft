# Build-Kontext ist das Projekt-Root (siehe docker-compose.yml, Service
# "export-tax-advisor"). Kein eigenständig laufender Dienst — wird per
# "docker compose run --rm export-tax-advisor ..." bei Bedarf gestartet,
# genau dann, wenn ihr einen Export für den Steuerberater braucht.
FROM python:3.12-slim

WORKDIR /app
COPY scripts/requirements.txt scripts/requirements.txt
RUN pip install --no-cache-dir -r scripts/requirements.txt

# Gleiche relative Verzeichnistiefe wie im Repo (scripts/.. -> connectors/common),
# damit export_for_tax_advisor.py's sys.path-Logik unverändert funktioniert.
COPY connectors/common ./connectors/common
COPY scripts/export_for_tax_advisor.py ./scripts/export_for_tax_advisor.py

ENTRYPOINT ["python", "scripts/export_for_tax_advisor.py"]
