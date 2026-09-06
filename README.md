# Belegwirtschaft

Lokal gehostetes Belegmanagement für die Firma: Belege aus Gmail und Amazon
werden automatisch eingesammelt, per OCR durchsuchbar gemacht und archiviert.
Alles läuft auf eigener Hardware — keine Cloud, keine Dritt-Dienste ausser den
zwei Quellen selbst (Gmail-API, amazon.de).

## Architektur

```
                    ┌─────────────────────────────────────────┐
                    │              Docker-Host                 │
                    │                                           │
  Gmail (IMAP/API)──┼──▶ connector-gmail  ──┐                  │
                    │                        │                  │
  amazon.de─────────┼──▶ connector-amazon ──┼──▶ Docspell       │
   (Playwright,     │                        │   Integration    │
    eigene Session)  │                        │   Endpoint       │
                    │                        ▼                  │
                    │                  docspell-restserver       │
                    │                        │                  │
                    │                  docspell-joex (OCR)       │
                    │                        │                  │
                    │              Postgres  +  Solr             │
                    │              (Volltextsuche)                │
                    │                        │                  │
                    │              ./data/  (alle Belege,         │
                    │               DB, Sessions — nur hier)      │
                    └─────────────────────────────────────────┘
                             ▲
                     Web-UI: http://localhost:7880
```

**Kernstück ist [Docspell](https://docspell.org)**, kein Eigenbau: OCR,
Volltextsuche, Tags/Correspondents/Ordner, Web-UI — alles bereits vorhanden
und in vielen Firmen/Haushalten im Einsatz. Selbst gebaut sind nur die beiden
**Connectors**, die Belege aus Gmail und Amazon automatisch anliefern.

Netzwerk-Design: Docspell-Kern + Datenbank + Solr haben **kein Internet**
(Docker-Netz `internal`, `internal: true`). Nur die beiden Connector-Container
hängen zusätzlich am Netz `internet` und dürfen nach aussen — und auch die nur
zu Google (Gmail-API) bzw. amazon.de.

## Warum Docspell (und nicht Paperless-ngx oder ein Eigenbau)

Recherchiert und verglichen:

- **[Paperless-ngx](https://github.com/paperless-ngx/paperless-ngx)** — der
  bekannteste Vertreter, sehr ausgereift, kann bereits von Haus aus ein
  IMAP-Postfach abholen ("Mail rules" — Anhänge aus passenden Mails werden
  automatisch importiert, quasi ein eingebauter, einfacherer Gmail-Connector).
  Starke Wahl, wenn reines Beleg-Postfach reicht.
- **[Docspell](https://docspell.org)** — konzeptionell sehr ähnlich (Django
  vs. Scala, sonst vergleichbarer Funktionsumfang: OCR via Tesseract,
  Volltextsuche via Solr, Tags/Correspondents/Ordner), zusätzlich mit
  **automatischer Erkennung von Datum, Betrag und Belegtyp per NLP** direkt aus
  dem Dokumenttext — für Buchhaltung/Belegwirtschaft der praktisch relevantere
  Fokus. Bietet ausserdem einen **Integration-Endpoint** (Upload per Secret,
  ohne Nutzer-Login) — genau die Schnittstelle, die automatisierte Connectors
  brauchen, ohne Klick-Bots gegen die eigene Web-UI zu bauen.
  → Deine Wahl, deshalb hier umgesetzt.
- **Eigenbau von Grund auf** — verworfen: OCR-Pipeline, Volltextsuche, UI,
  Nutzerverwaltung selbst zu bauen dauert Monate und liefert am Ende weniger,
  als eine der beiden obigen, seit Jahren gehärteten Lösungen schon kann.

## Was die Connectors tun (und was nicht)

### Gmail — stabil, offizielle API
OAuth2 mit Scope `gmail.readonly` (rein lesend, nichts löschen/verschieben/
versenden möglich). Regeln in [`config/sources.yaml`](config/sources.yaml)
matchen per Gmail-Suchsyntax (Absender, Betreff, Anhang-Typ) und definieren,
mit welchem Correspondent/Tag/Ordner ein Treffer in Docspell landet. PDF-
Anhänge werden direkt übernommen. Setup: [`connectors/gmail/README.md`](connectors/gmail/README.md).

### Amazon — funktioniert, aber fragil (keine offizielle API)
Amazon hat den früheren CSV-Export "Order History Reports" 2023 abgeschaltet;
für Privatkonten existiert keine stabile Schnittstelle. Der Connector nutzt
Playwright mit **deiner eigenen, manuell erstellten Login-Session**
(Cookies — kein Passwort wird gespeichert oder automatisiert eingegeben) und
ruft damit periodisch die Bestellhistorie auf, um Rechnungen herunterzuladen.
Das bricht gelegentlich bei Layout-Änderungen von Amazon oder wenn die Session
abläuft — beides mit klarer Fehlermeldung, die sagt, was zu tun ist. Setup:
[`connectors/amazon/README.md`](connectors/amazon/README.md).

### AliExpress — bewusst (noch) nicht umgesetzt
Auf deinen Wunsch hin erstmal ausgeklammert: AliExpress bietet für
Bestellhistorie keine öffentliche API, der einzige Weg wäre Browser-
Automatisierung wie bei Amazon — dort aber deutlich instabiler (aggressivere
Bot-Erkennung, häufigere Captchas/2FA-Abbrüche). Bis das sauber lösbar ist,
zwei pragmatische Übergangswege:
1. AliExpress-Bestellbestätigungen laufen ohnehin oft per Mail ein → eine
   Regel dafür in `config/sources.yaml` ergänzen (analog zur Amazon-Regel),
   dann übernimmt sie der Gmail-Connector automatisch mit.
2. Rechnung manuell als PDF speichern und in Docspells Web-UI hochladen
   (Drag & Drop) — auch das landet sofort durchsuchbar in der Ablage.

## Datenschutz / DSGVO — Leitlinien dieses Aufbaus
- **Alles lokal**: Belege, Datenbank, OCR-Index, Sessions liegen ausschliesslich
  unter `./data` auf deinem Server/NAS. Keine Cloud-OCR, kein Upload an
  Dritt-Dienste.
- **Minimalprinzip bei Zugriffsrechten**: Gmail-Scope ist rein lesend; Amazon-
  Session ist deine eigene, keine gespeicherten Passwörter.
- **Verschlüsselung**: Für Belege mit personenbezogenen/sensiblen Daten
  empfiehlt sich zusätzlich Festplattenverschlüsselung des Host-Systems
  (LUKS/BitLocker/FileVault) — das deckt dieses Setup nicht selbst ab.
- **Backups**: `./data` regelmässig sichern (verschlüsselt!), sonst ist ein
  Festplattendefekt gleichbedeutend mit Belegverlust.
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
./scripts/setup.sh                     # legt ./data und .env an
# Danach je einmal lokal (nicht im Container):
#   connectors/gmail/README.md   folgen (OAuth-Login)
#   connectors/amazon/README.md  folgen (Session-Login)
docker compose up -d
open http://localhost:7880             # ersten Docspell-Account anlegen
```

**Hinweis zur Docspell-Konfiguration:** `docker-compose.yml` und
`docspell/*.conf` sind nach bestem Wissen aus der öffentlichen Docspell-
Dokumentation zusammengestellt. Der Netzwerkzugriff auf docspell.org war beim
Erstellen dieses Setups technisch blockiert, daher bitte vor dem ersten Start
einmal gegen https://docspell.org/docs/install/docker/ gegenchecken (Image-
Tags, exakte Env-Var-Namen für deine Docspell-Version).

## Verzeichnisstruktur

```
docker-compose.yml          # Docspell-Kern + beide Connectors
docspell/                   # Docspell-Konfigurationsdateien
config/sources.yaml         # Gmail-Erkennungsregeln (Absender → Tags/Ordner)
connectors/
  common/                   # gemeinsamer Docspell-Upload-Client + Dedupe-State
  gmail/                    # Gmail-Connector (OAuth2, gmail.readonly)
  amazon/                   # Amazon-Connector (Playwright, eigene Session)
data/                       # ALLE persistenten Daten (git-ignoriert)
```

## Nächste sinnvolle Ausbaustufen
- AliExpress-Mailregel ergänzen (siehe oben), sobald erste Bestellbestätigungen
  im Postfach liegen — kein Codeaufwand, nur ein Eintrag in `sources.yaml`.
- Docspells eingebaute "ScanMailbox"-Funktion als zweite, redundante
  Gmail-Anbindung testen, falls der eigene Connector zu wartungsintensiv wird.
- Automatisches Tagging nach Beleg-Betrag/Datum über Docspells eigene
  NLP-Erkennung weiter verfeinern (Regex-Zuordnungen in Docspell selbst, nicht
  in diesem Repo).
