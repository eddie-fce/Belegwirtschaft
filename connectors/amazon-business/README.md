# Amazon-Business-Connector — Setup

Anders als beim privaten Amazon-Konto (siehe `connectors/amazon/`) gibt es für
**Amazon Business** eine offizielle, dokumentierte REST-API (Reconciliation
API + Document API, authentifiziert über Login with Amazon / LWA-OAuth2).
Deshalb kein Playwright/Browser-Scraping hier — dafür ein einmaliger,
etwas aufwändigerer Registrierungsprozess bei Amazon, den nur ihr als
Kontoinhaber durchführen könnt.

## 1. Als Amazon-Business-API-Entwickler registrieren (einmalig, dauert ggf. einige Tage)

1. Auf https://docs.business.amazon.com/docs/register-as-a-developer den
   "Developer Registration Access Form" (DRAF) ausfüllen — Amazon prüft dabei
   eure Geschäftsidentität, teils inkl. Video-Call-Verifikation.
2. Nach Freischaltung: im **Solution Provider Portal** eine Anwendung anlegen
   und ein **LWA-Security-Profile** erstellen → daraus ergeben sich
   `client_id` und `client_secret`.
3. Beide Werte in `.env` eintragen:
   ```
   AMAZON_BUSINESS_CLIENT_ID=...
   AMAZON_BUSINESS_CLIENT_SECRET=...
   ```

## 2. Einmalig lokal einloggen

```bash
cd connectors/amazon-business
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python amazon_business_connector.py --login
```

Öffnet einen Login-with-Amazon-Consent-Link — im Browser mit dem
Amazon-Business-Konto bestätigen, den `code`-Parameter aus der
Weiterleitungs-URL zurück ins Terminal einfügen. Danach liegt ein
Refresh-Token unter `secrets/token.json` (git-ignoriert), mit dem der
Connector im Container headless weiterläuft.

## Wichtiger Hinweis zur Genauigkeit dieses Codes

Der Netzwerkzugriff auf `developer-docs.amazon.com` war beim Schreiben dieses
Connectors technisch blockiert. Die grundlegenden API-Konzepte (Reconciliation
API liefert Bestell-/Rechnungsreferenzen, Document API liefert das PDF dazu)
sind durch öffentlich auffindbare Amazon-Dokutitel belegt — die *exakten*
Endpunkt-Pfade, der Basis-Host je Region (`AMAZON_BUSINESS_API_BASE_URL` in
`.env`) und einzelne JSON-Feldnamen in `amazon_business_connector.py` sind mit
`# ADJUST` markiert und müssen einmal gegen die echte Doku geprüft werden,
sobald ihr als Entwickler Zugriff darauf habt:
- https://developer-docs.amazon.com/amazon-business/docs/reconciliation-api-v1-reference
- https://developer-docs.amazon.com/amazon-business/docs/document-api
- https://developer-docs.amazon.com/amazon-business/docs/retrieving-invoice-details

Erster Testlauf am besten mit `docker compose logs -f connector-amazon-business`
im Blick, um schnell zu sehen, ob ein Endpunkt-Pfad angepasst werden muss.

## Verhältnis zum alten Playwright-Connector
`connectors/amazon/` (Browser-Automatisierung) bleibt im Repo als Fallback für
private (Nicht-Business-)Amazon-Konten, ist aber standardmässig nicht mehr in
`docker-compose.yml` aktiv, seit dieser Connector für Amazon Business
umgesetzt ist. Beide gleichzeitig laufen zu lassen ergibt keinen Sinn, wenn
alle Bestellungen ohnehin über das Business-Konto laufen.
