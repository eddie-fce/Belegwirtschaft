# Belegwirtschaft

Lokal gehostetes Belegmanagement für die Firma: Belege aus Gmail werden
automatisch eingesammelt, dazu manuelles Scannen per Handy und (1-2x im Jahr)
ein Amazon-Business-Bulk-Export — alles per OCR durchsuchbar gemacht und
archiviert. Alles läuft auf eigener Hardware — keine Cloud, keine
Dritt-Dienste ausser der Quelle selbst (Gmail-API, optional ein selbst
gehosteter ntfy-Server für Alarme).

## Architektur

```
                    ┌───────────────────────────────────────────────┐
                    │                  Docker-Host                    │
                    │                                                 │
  Gmail (API)───────┼──▶ connector-gmail             ──┐             │
                    │                                   ├──▶ Docspell │
  Handy (Syncthing)──┼──▶ connector-dropzone           ──┘  Integration│
  Amazon-Export       │        ▲                             Endpoint  │
   (1-2x/Jahr,         │        │                                      │
    manuelles ZIP)      │  entpacken in ./data/dropzone                │
                    │                                   │             │
                    │                                   ▼             │
                    │                            docspell-restserver   │
                    │                                   │             │
                    │                            docspell-joex (OCR,   │
                    │                             Klassifikator)        │
                    │                                   │             │
                    │                        Postgres  +  Solr         │
                    │                        (Volltextsuche)            │
                    │                                   │             │
                    │                        ./data/  (alle Belege,     │
                    │                         DB, Sessions — nur hier)    │
                    └───────────────────────────────────────────────┘
                             ▲                        ▲
                     Web-UI: http://localhost:7880     optional: ntfy-Alarme
                                                        bei gestörten Connectors
```

Nur zwei Connector-Container: **Gmail** (echte Automatisierung, läuft dauerhaft)
und **Dropzone** (nimmt sowohl Handy-Scans als auch den seltenen
Amazon-Business-Export entgegen). Für Amazon gibt es bewusst **keinen eigenen
Connector-Code**: Bei 1-2 Exporten im Jahr wäre sowohl eine
Amazon-Entwickler-Registrierung als auch eine gegen Amazons UI geschriebene
Browser-Automatisierung mehr Aufwand/Fragilität, als sie einsparen — Details
dazu in [`docs/amazon-business-export.md`](docs/amazon-business-export.md).

**Kernstück ist [Docspell](https://docspell.org)**, kein Eigenbau: OCR,
Volltextsuche, Tags/Correspondents/Ordner, Web-UI, ein lernender Klassifikator
für Auto-Tagging — alles bereits vorhanden und in vielen Firmen/Haushalten im
Einsatz. Selbst gebaut sind nur die **Connectors**, die Belege automatisch
anliefern, plus ein paar Betriebs-Skripte drumherum (Backup, Export, Alarme).

Netzwerk-Design: Docspell-Kern + Datenbank + Solr haben **kein Internet**
(Docker-Netz `internal`, `internal: true`). Nur die Connector-Container hängen
zusätzlich am Netz `internet` und dürfen nach aussen — und auch die nur zu
Google (Gmail-API) bzw. dem optionalen ntfy-Server.

## Warum Docspell (und nicht Paperless-ngx oder ein Eigenbau)

Recherchiert und verglichen:

- **[Paperless-ngx](https://github.com/paperless-ngx/paperless-ngx)** — der
  bekannteste Vertreter, sehr ausgereift, kann bereits von Haus aus ein
  IMAP-Postfach abholen ("Mail rules"). Starke Wahl, wenn reines
  Beleg-Postfach reicht.
- **[Docspell](https://docspell.org)** — konzeptionell sehr ähnlich, zusätzlich
  mit **automatischer Erkennung von Datum, Betrag und Belegtyp per NLP**
  direkt aus dem Dokumenttext und einem lernenden Klassifikator für
  Auto-Tagging — für Buchhaltung/Belegwirtschaft der praktisch relevantere
  Fokus. Bietet ausserdem einen **Integration-Endpoint** (Upload per Secret,
  ohne Nutzer-Login) — genau die Schnittstelle, die automatisierte Connectors
  brauchen. → Deine Wahl, deshalb hier umgesetzt.
- **Eigenbau von Grund auf** — verworfen: OCR-Pipeline, Volltextsuche, UI,
  Nutzerverwaltung selbst zu bauen dauert Monate und liefert am Ende weniger,
  als eine der beiden obigen, seit Jahren gehärteten Lösungen schon kann.

## Die Connectors im Überblick

### Gmail — stabil, offizielle API
OAuth2 mit Scope `gmail.readonly` (rein lesend, nichts löschen/verschieben/
versenden möglich). Regeln in [`config/sources.yaml`](config/sources.yaml)
matchen per Gmail-Suchsyntax (Absender, Betreff, Anhang-Typ) und definieren,
mit welchem Correspondent/Tag/Ordner ein Treffer in Docspell landet.
Zusätzlich versucht der Connector, den Rechnungsbetrag direkt aus dem
Mailtext zu lesen (`connectors/common/amount_extract.py`) und hängt ihn lesbar
an den Dateinamen an (z.B. `invoice_47.98EUR.pdf`) — damit siehst du in
Docspell auf einen Blick, ob der von OCR erkannte Betrag zum tatsächlichen
Rechnungsbetrag aus der Mail passt, ohne ein separates, fehleranfälliges
Abgleich-Tool zu brauchen. Setup: [`connectors/gmail/README.md`](connectors/gmail/README.md).

### Amazon Business — manueller Bulk-Export, 1-2x im Jahr
Kein Connector-Code: Amazon Business hat einen eingebauten Sammel-Export
("Business Analytics" → Berichte → Bestellungen → Zeitraum wählen →
Rechnungen als ZIP herunterladen, bis zu 2000 Dokumente pro Durchgang, bis zu
5 Jahre rückwirkend). ZIP entpacken, PDFs in `./data/dropzone` legen — der
**Dropzone-Connector** (s.u.) lädt sie automatisch nach Docspell hoch. Details
und Begründung, warum hier bewusst nicht automatisiert wird:
[`docs/amazon-business-export.md`](docs/amazon-business-export.md).

### AliExpress — über Gmail abgedeckt
Kein eigener Browser-Connector (zu instabil, siehe unten), stattdessen eine
Regel in `sources.yaml`, die AliExpress-Bestellmails über den Gmail-Connector
mitnimmt — deckt nicht jede Bestellung ab (nicht jeder Verkäufer schickt eine
Rechnungsmail), aber ohne die Fragilität eines eigenen Scrapers. Für Lücken:
Rechnung manuell als PDF speichern und über die **Dropzone** (s.u.) oder
direkt in Docspells Web-UI hochladen.

### Dropzone — manuelles Scannen per Handy
Ein Ordner (`./data/dropzone`, per Syncthing vom Handy synchronisiert)
wird beobachtet; jede neue Datei (Foto von Restaurant-/Park-/Tankbeleg) wird
automatisch mit Tag `Manuell` nach Docspell hochgeladen und danach in
`verarbeitet/` verschoben. Setup: [`connectors/dropzone/README.md`](connectors/dropzone/README.md).

## Betrieb & Ausfallsicherheit

### Benachrichtigungen bei gestörten Connectors
Jeder Connector zählt aufeinanderfolgende Fehlschläge (`connectors/common/state.py`)
und schickt ab einer konfigurierbaren Schwelle (`*_ALERT_AFTER_FAILURES` in
`.env`, Default 3) eine Push-Benachrichtigung über
[ntfy](https://github.com/binwiederhier/ntfy) — z.B. bei einer nicht mehr
abrufbaren Gmail-API. Ohne gesetzte `NTFY_URL`/`NTFY_TOPIC` in `.env` sind
Benachrichtigungen einfach aus (kein Fehler). Am datenschutzfreundlichsten:
ntfy selbst hosten statt ntfy.sh zu nutzen.

### Backups
`scripts/backup.sh` sichert Datenbank-Dump + `./data` client-seitig
verschlüsselt per [restic](https://restic.net) auf ein Ziel eurer Wahl
(externe Platte, NAS, auch ein Cloud-Bucket — die Verschlüsselung passiert
*vor* dem Verlassen dieses Rechners, das Ziel muss also nicht vertrauenswürdig
sein). Konfiguration über `RESTIC_REPOSITORY`/`RESTIC_PASSWORD` in `.env`.
Einrichtung als täglicher Cron-Job ist im Skript-Kopf dokumentiert — bewusst
nicht automatisch eingerichtet, damit nicht ungefragt in eure Systemd/Cron-
Konfiguration eingegriffen wird.

### Steuerberater-Export
`scripts/export_for_tax_advisor.py --from 2026-01-01 --to 2026-03-31 --out export.zip`
packt alle als "Rechnung" getaggten Belege eines Zeitraums als ZIP mit
Manifest-CSV. **Best-effort**: nutzt Docspells authentifizierte Such-/
Download-API, die mangels Netzwerkzugriff auf docspell.org beim Bau dieses
Repos nicht live verifiziert werden konnte (siehe Kommentare in
`connectors/common/docspell_query.py`) — ersten Testlauf mit kleinem Zeitraum
machen, bevor es Teil eines wiederkehrenden Ablaufs wird. Braucht einen
normalen Docspell-Login (`DOCSPELL_ACCOUNT`/`DOCSPELL_PASSWORD` in `.env`),
nicht das Integration-Secret.

### Auto-Tagging / Klassifikator
Docspells eingebauter Klassifikator lernt aus bereits korrekt getaggten
Belegen und schlägt bei neuen, unbekannten Absendern passende Tags vor.
Aktivierung/Feinschliff über `docspell/docspell-joex.conf` (Kommentare dort)
— am wirkungsvollsten, sobald ein paar Dutzend Belege pro Correspondent
sauber getaggt sind.

### Versionspinning
`docspell/restserver` und `docspell/joex` laufen auf einer festen, in `.env`
gepinnten Version (`DOCSPELL_VERSION`) statt `:latest` — ein Update im
Hintergrund soll den Stack nicht überraschend brechen. Vor dem ersten Start
aktuellen Tag auf https://github.com/docspell/docspell/releases prüfen.

## Datenschutz / DSGVO — Leitlinien dieses Aufbaus
- **Alles lokal**: Belege, Datenbank, OCR-Index, Sessions liegen ausschliesslich
  unter `./data` auf deinem Server/NAS. Keine Cloud-OCR, kein Upload an
  Dritt-Dienste.
- **Minimalprinzip bei Zugriffsrechten**: Gmail-Scope ist rein lesend; der
  Amazon-Bulk-Export ist ein manueller Download durch euch selbst — keine
  Amazon-Zugangsdaten liegen je in diesem System.
- **Verschlüsselung**: Für Belege mit personenbezogenen/sensiblen Daten
  empfiehlt sich zusätzlich Festplattenverschlüsselung des Host-Systems
  (LUKS/BitLocker/FileVault) — das deckt dieses Setup nicht selbst ab.
- **Backups**: siehe oben — `scripts/backup.sh`, client-seitig verschlüsselt.
- **Zugriff von aussen**: Der Docspell-Port ist bewusst nur an `127.0.0.1`
  gebunden — Zugriff von unterwegs nur per SSH-Tunnel oder VPN, nicht über
  einen offen ins Internet gestellten Port.
- **Aufbewahrungsfristen**: In Docspell lassen sich Tags/Ordner für
  gesetzliche Aufbewahrungsfristen (i.d.R. 10 Jahre für Rechnungen in
  Deutschland/Österreich, §147 AO bzw. §212 UGB) abbilden — das Löschen nach
  Fristablauf ist bewusst manuell zu halten und nicht automatisiert.

## Setup

```bash
git clone <dieses Repo>
cd Belegwirtschaft
./scripts/setup.sh                        # legt ./data (inkl. Dropzone) und .env an
# Danach je einmal lokal (nicht im Container):
#   connectors/gmail/README.md            folgen (OAuth-Login)
#   connectors/dropzone/README.md         folgen (Syncthing einrichten, optional)
docker compose up -d                      # startet Docspell + Gmail + Dropzone
open http://localhost:7880                # ersten Docspell-Account anlegen

# Amazon Business: 1-2x im Jahr Business-Analytics-Export in ./data/dropzone
# entpacken, siehe docs/amazon-business-export.md — kein weiterer Setup-Schritt
# nötig, der Dropzone-Connector läuft schon.
```

**Hinweis zur Docspell-Konfiguration:** `docker-compose.yml` und
`docspell/*.conf` sind nach bestem Wissen aus der öffentlichen Docspell-
Dokumentation zusammengestellt. Der Netzwerkzugriff auf docspell.org war beim
Erstellen dieses Setups technisch blockiert, daher bitte vor dem ersten Start
einmal gegen https://docspell.org/docs/install/docker/ gegenchecken (Image-
Tag in `DOCSPELL_VERSION`, exakte Env-Var-Namen). Gleiches gilt für die
authentifizierte Such-API hinter dem Steuerberater-Export
(`connectors/common/docspell_query.py`) — dort ausführlicher kommentiert.

## Verzeichnisstruktur

```
docker-compose.yml          # Docspell-Kern + Connectors
docspell/                   # Docspell-Konfigurationsdateien
config/sources.yaml         # Gmail-Erkennungsregeln (Absender → Tags/Ordner)
docs/
  amazon-business-export.md # Anleitung: manueller Amazon-Business-Rechnungsexport
connectors/
  common/                   # Docspell-Clients (Upload + authentifizierte Suche),
                             # Dedupe-/Fehler-State, ntfy-Alarme, Betrag-Extraktion
  gmail/                    # Gmail-Connector (OAuth2, gmail.readonly)
  dropzone/                 # Manuelles Scannen per Handy + Amazon-Bulk-Export-Aufnahme
scripts/
  setup.sh                  # Einmaliges Setup (Verzeichnisse, .env)
  backup.sh                 # Verschlüsseltes restic-Backup
  export_for_tax_advisor.py # ZIP-Export getaggter Belege für einen Zeitraum
data/                       # ALLE persistenten Daten (git-ignoriert)
```

## Offene Punkte, die vor dem produktiven Einsatz noch geprüft werden sollten
- Docspell-Image-Tags/Env-Var-Namen gegen die aktuelle Doku (s.o.).
- Die authentifizierte Docspell-Such-API (`docspell_query.py`) einmal gegen
  eure laufende Instanz testen, bevor der Steuerberater-Export in einen festen
  Ablauf übernommen wird.
