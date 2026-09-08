# Build-Kontext ist das Projekt-Root (siehe docker-compose.yml).
FROM python:3.12-slim

WORKDIR /app
COPY connectors/mirror-sync/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY connectors/common ./common
COPY connectors/mirror-sync/mirror_sync.py .

CMD ["python", "mirror_sync.py"]
