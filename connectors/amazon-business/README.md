# Amazon Business — Setup

Es gibt zwei Wege, Rechnungen aus Amazon Business zu bekommen. Ohne
Entwickler-Registrierung bei Amazon nutzt ihr **Weg A** — das ist der
Standard in diesem Setup. **Weg B** (offizielle API) liegt fertig im Repo,
falls ihr später doch Entwicklerzugang bekommt.

## Weg A: Manueller Bulk-Export + Dropzone (kein Entwicklerkonto nötig)

Amazon Business hat einen eingebauten Sammel-Export für Rechnungen — kein
API-Zugang, keine Registrierung, nur ein paar Klicks:

1. Bei business.amazon.de einloggen, oben im Konto-Menü **"Business
   Analytics"** öffnen.
2. Im Reiter **"Berichte"** den Bericht **"Bestellungen"** wählen, Zeitraum
   einstellen (z.B. letzter Monat).
3. Gewünschte Bestellungen auswählen (oder alle) → **"Auftragsdokumente
   abrufen"** bzw. "Get order documents" → **Rechnungen** auswählen →
   herunterladen. Amazon liefert ein ZIP mit allen Rechnungs-PDFs
   (bis zu 2000 pro Durchgang, bis zu 5 Jahre rückwirkend verfügbar).
4. Das ZIP entpacken und die PDFs in `./data/dropzone` legen (denselben
   Ordner, den der [Dropzone-Connector](../dropzone/README.md) für
   Handy-Scans beobachtet) — der Connector lädt sie automatisch mit Tag
   `Manuell` nach Docspell hoch.

Praktisch als wiederkehrende Aufgabe: einmal im Monat 5 Minuten, dafür ohne
jede Abhängigkeit von Amazons Seitenlayout oder einer API-Registrierung, die
Amazon ablehnen könnte. Wer mag, kann Schritt 3+4 später automatisieren
(siehe Abschnitt "Automatisierung" unten) — für den Start reicht der manuelle
Weg völlig.

### Warum nicht automatisiert per Browser-Bot?
Weil ich den genauen Klickpfad (Menütexte, Reihenfolge der Dropdowns) nicht
gegen die echte Amazon-Business-UI testen konnte — ein blind geschriebener
Bot dafür wäre genauso rätselhaft-fragil wie das Erraten von API-Endpunkten
in Weg B. Lieber ehrlich ein paar manuelle Klicks als ein Automatisierungs-
Versprechen, das beim ersten Versuch nicht hält.

## Weg B: Offizielle API (nur mit Amazon-Entwicklerzugang)

Falls ihr später doch als Amazon-Business-API-Entwickler registriert seid
(Identitätsprüfung durch Amazon, siehe unten) — der fertige Connector
`amazon_business_connector.py` nutzt die Reconciliation API + Document API
über Login-with-Amazon-OAuth2, komplett ohne Browser-Automatisierung.

1. Auf https://docs.business.amazon.com/docs/register-as-a-developer den
   "Developer Registration Access Form" (DRAF) ausfüllen — Amazon prüft dabei
   eure Geschäftsidentität, teils inkl. Video-Call-Verifikation.
2. Nach Freischaltung: im **Solution Provider Portal** eine Anwendung anlegen
   und ein **LWA-Security-Profile** erstellen → daraus ergeben sich
   `client_id` und `client_secret`, in `.env` eintragen
   (`AMAZON_BUSINESS_CLIENT_ID`/`AMAZON_BUSINESS_CLIENT_SECRET`).
3. Einmalig lokal einloggen:
   ```bash
   cd connectors/amazon-business
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   python amazon_business_connector.py --login
   ```
   Öffnet einen Login-with-Amazon-Consent-Link — im Browser bestätigen, den
   `code`-Parameter aus der Weiterleitungs-URL zurück ins Terminal einfügen.
4. Aktivieren: `docker compose --profile amazon-business-api up -d connector-amazon-business`
   (standardmässig aus, da ohne Entwicklerzugang nicht nutzbar).

**Wichtiger Hinweis zur Genauigkeit dieses Codes:** Der Netzwerkzugriff auf
`developer-docs.amazon.com` war beim Schreiben dieses Connectors technisch
blockiert. Die grundlegenden API-Konzepte sind durch öffentlich auffindbare
Amazon-Dokutitel belegt — die *exakten* Endpunkt-Pfade, der Basis-Host je
Region (`AMAZON_BUSINESS_API_BASE_URL` in `.env`) und einzelne JSON-Feldnamen
in `amazon_business_connector.py` sind mit `# ADJUST` markiert und müssen
einmal gegen die echte Doku geprüft werden:
- https://developer-docs.amazon.com/amazon-business/docs/reconciliation-api-v1-reference
- https://developer-docs.amazon.com/amazon-business/docs/document-api
- https://developer-docs.amazon.com/amazon-business/docs/retrieving-invoice-details

## Verhältnis zum privaten Amazon-Connector
`connectors/amazon/` (Browser-Automatisierung gegen die normale, private
Bestellhistorie) ist für Konten ohne Business-Analytics-Zugang gedacht —
für ein Amazon-Business-Konto irrelevant, bleibt aber als Referenz im Repo
(Docker-Compose-Profil `legacy-private-amazon`, standardmässig aus).
