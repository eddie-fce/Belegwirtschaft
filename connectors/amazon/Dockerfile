# Build-Kontext ist das Projekt-Root (siehe docker-compose.yml).
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app
COPY connectors/amazon/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY connectors/common ./common
COPY connectors/amazon/amazon_connector.py .

CMD ["python", "amazon_connector.py"]
