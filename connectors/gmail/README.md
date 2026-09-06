# Gmail-Connector — Setup

1. **Google Cloud Projekt anlegen** (kostenlos): https://console.cloud.google.com/
2. **Gmail API aktivieren**: APIs & Services → Library → "Gmail API" → Enable.
3. **OAuth-Consent-Screen** einrichten: User Type "External" (reicht für den eigenen
   Testnutzer), Scope `gmail.readonly` hinzufügen. Solange die App im Status
   "Testing" bleibt, muss dein eigenes Gmail-Konto als Testnutzer eingetragen werden.
4. **OAuth-Client erstellen**: Typ **Desktop-App**. Die heruntergeladene JSON-Datei
   als `secrets/credentials.json` in diesem Ordner ablegen (Ordner `secrets/` selbst
   anlegen — er ist per `.gitignore` von Git ausgeschlossen).
5. **Einmalig lokal einloggen** (nicht im Container, da ein Browser-Fenster
   aufgeht):
   ```bash
   cd connectors/gmail
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   python gmail_connector.py --login
   ```
   Das erzeugt `secrets/token.json`. Danach kann der Connector im Docker-Container
   headless weiterlaufen (`docker compose up -d connector-gmail`) und erneuert das
   Token automatisch, solange Google es nicht widerruft.

## Was der Connector NICHT kann
- Nichts löschen, verschieben oder versenden (Scope ist rein lesend).
- Keine Mails ausserhalb der Regeln in `config/sources.yaml` anfassen.

## Regeln anpassen
Siehe `config/sources.yaml` im Projekt-Root — Gmail-Suchsyntax, pro Regel ein
Correspondent/Tags/Ordner-Mapping für Docspell.
