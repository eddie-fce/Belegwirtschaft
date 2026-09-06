# Build-Kontext ist das Projekt-Root (siehe docker-compose.yml).
FROM python:3.12-slim

WORKDIR /app
COPY connectors/dropzone/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY connectors/common ./common
COPY connectors/dropzone/dropzone_connector.py .

CMD ["python", "dropzone_connector.py"]
