# Dropzone-Connector + Syncthing — Setup

Für Belege, die nie digital ankommen: Restaurant-Quittung, Parkschein,
Tankbeleg — mit dem Handy fotografieren/scannen, landet automatisch in
Docspell. Genauso der Weg für den **Amazon-Business-Bulk-Export**: das 1-2x
im Jahr heruntergeladene ZIP mit Rechnungen (siehe
[`docs/amazon-business-export.md`](../../docs/amazon-business-export.md))
einfach hier entpacken statt fotografieren — der Connector unterscheidet
nicht zwischen den Quellen, er lädt einfach jede neue Datei hoch.

Syncthing läuft als Teil dieses Docker-Compose-Stacks (Service `syncthing`)
und synct direkt zwischen deinem Handy und `./data/dropzone` — keine
Cloud-Zwischenstation, keine separate App-Center-Installation nötig.

## 1. Syncthing-Weboberfläche öffnen

Der Web-UI-Port ist bewusst nur an `127.0.0.1` gebunden (wie Docspell). Von
deinem Rechner aus per SSH-Tunnel zur NAS:
```bash
ssh -L 8384:localhost:8384 admin@<nas-ip>
```
Dann im Browser `http://localhost:8384` öffnen.

## 2. Handy koppeln

1. Auf dem Handy Syncthing installieren (Android: offizielle
   [Syncthing-App](https://play.google.com/store/apps/details?id=com.nutomic.syncthingandroid);
   iOS: [Möbius Sync](https://apps.apple.com/app/m%C3%B6bius-sync/id1539203216),
   da es keine offizielle Syncthing-iOS-App gibt).
2. In der NAS-Weboberfläche (aus Schritt 1): **"Gerät hinzufügen"** → die
   Geräte-ID vom Handy eintragen (steht in der Handy-App unter
   Einstellungen). Beide Seiten müssen sich gegenseitig akzeptieren.
3. Auf der NAS-Seite den vorhandenen Ordner **"dropzone"** (zeigt auf
   `./data/dropzone`) für das neu gekoppelte Handy freigeben.
4. Auf dem Handy: den freigegebenen Ordner annehmen, als lokalen Zielordner
   z.B. einen eigenen "Belege"-Ordner wählen.

## 3. Scan-App einrichten

Rohe Fotos funktionieren, aber eine echte Scan-App (zuschneiden, Kontrast
erhöhen) verbessert die OCR-Erkennung in Docspell deutlich:
- **iOS**: Notizen-App → Kamera-Symbol → "Dokumente scannen" → als PDF in den
  gekoppelten Syncthing-Ordner exportieren ("In Dateien sichern").
- **Android**: z.B. Google Drive (integrierter Scanner) oder
  [Genius Scan](https://play.google.com/store/apps/details?id=com.thegrizzlylabs.geniusscan.free) —
  Export-Ziel auf den Syncthing-Ordner stellen.

Sobald die Datei im synchten Ordner landet, holt sie Syncthing automatisch
nach `./data/dropzone` auf der NAS, und der Dropzone-Connector lädt sie von
dort (Standard-Prüfintervall 60s) nach Docspell hoch.

## Verhalten des Dropzone-Connectors
- Neue Dateien werden alle `DROPZONE_POLL_INTERVAL_SECONDS` (Default 60s)
  geprüft und nach Docspell hochgeladen, mit den Tags `Manuell`/`Unsortiert`
  (in Docspells UI danach normal nachsortieren).
- Nach erfolgreichem Upload wird die Datei nach `verarbeitet/` verschoben
  (nicht gelöscht).
- Bei fehlgeschlagenem Upload landet die Datei in `fehlgeschlagen/` — von dort
  kannst du sie manuell in Docspells Web-UI hochladen oder das Problem
  beheben und zurück in den Dropzone-Ordner legen.

## Ports, die vom Handy erreichbar sein müssen
`22000/tcp+udp` (Sync-Protokoll) und `21027/udp` (lokale Geräte-Erkennung) —
beide sind in `docker-compose.yml` auf die reale Netzwerkschnittstelle der
NAS gemappt (nicht nur `127.0.0.1`), müssen also im selben WLAN/LAN
erreichbar sein. Für Sync von unterwegs (ausserhalb des Heimnetzes) zusätzlich
Port-Weiterleitung am Router oder ein VPN zur NAS einrichten.
