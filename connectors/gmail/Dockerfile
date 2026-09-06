# Build-Kontext ist das Projekt-Root (siehe docker-compose.yml), damit "common/"
# mit reinkopiert werden kann.
FROM python:3.12-slim

WORKDIR /app
COPY connectors/gmail/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY connectors/common ./common
COPY config/sources.yaml /config/sources.yaml
COPY connectors/gmail/gmail_connector.py .

CMD ["python", "gmail_connector.py"]
