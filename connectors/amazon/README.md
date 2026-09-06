# Amazon-Connector — Setup

Es gibt keine offizielle API, mit der ein privates Amazon-Konto seine
Bestellhistorie/Rechnungen automatisiert abrufen kann (Amazon hat den früheren
CSV-Export "Order History Reports" 2023 abgeschaltet). Dieser Connector
automatisiert daher das, was du sonst manuell im Browser tätest — eingeloggt
Rechnungen aufrufen und herunterladen.

## Setup (einmalig, lokal — nicht im Container)

```bash
cd connectors/amazon
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python amazon_connector.py --login
```

Es öffnet sich ein sichtbares Browser-Fenster. Dort loggst **du** dich normal
bei Amazon ein (inkl. 2FA, falls aktiv) — der Connector tippt nichts automatisch
ein und sieht dein Passwort nie. Sobald du auf der Bestellübersicht bist, im
Terminal ENTER drücken. Die Session wird als `secrets/storage_state.json`
gespeichert (Cookies — kein Passwort!) und ist per `.gitignore` von Git
ausgeschlossen.

Danach läuft der Connector headless im Container weiter
(`docker compose up -d connector-amazon`).

## Wichtige Einschränkungen
- **Session läuft irgendwann ab** (Amazon meldet nach einiger Zeit oder bei
  verdächtiger Aktivität ab) → dann einfach `--login` erneut ausführen.
- **Layout-Änderungen brechen die CSS-Selektoren.** Alle Selektoren stehen
  gesammelt am Anfang von `amazon_connector.py` — dort zuerst nachsehen, wenn
  keine Bestellungen mehr gefunden werden.
- **Nicht jede Bestellung hat eine klassische PDF-Rechnung** (v.a. Marktplatz-
  Verkäufer, digitale Güter). Für diese Fälle wird ersatzweise die
  Bestelldetails-Seite als PDF gerendert.
- Nur für **dein eigenes Konto** gedacht, mit eingebauten Pausen zwischen
  Anfragen — kein Massen-Scraping.
