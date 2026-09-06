# Build-Kontext ist das Projekt-Root (siehe docker-compose.yml).
FROM python:3.12-slim

WORKDIR /app
COPY connectors/amazon-business/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY connectors/common ./common
COPY connectors/amazon-business/amazon_business_connector.py .

CMD ["python", "amazon_business_connector.py"]
