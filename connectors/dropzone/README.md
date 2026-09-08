# Dropzone-Connector + Syncthing — Setup

Für Belege, die nie digital ankommen: Restaurant-Quittung, Parkschein,
Tankbeleg — mit dem Handy fotografieren/scannen, landet automatisch in
Docspell. Genauso der Weg für den **Amazon-Business-Bulk-Export**: das 1-2x
im Jahr heruntergeladene ZIP mit Rechnungen (siehe
[`docs/amazon-business-export.md`](../../docs/amazon-business-export.md))
einfach hier entpacken statt fotografieren — der Connector unterscheidet
nicht zwischen den Quellen, er lädt einfach jede neue Datei hoch.

**Zwei Unterordner statt einem:**
- `./data/dropzone/eingang/` — empfangene Belege (Einkäufe, Lieferantenrechnungen,
  Amazon-Business-Export). Landet im Ordnerbaum unter `.../<Jahr>/Eingang/<Monat>/`.
- `./data/dropzone/ausgang/` — Rechnungen, die die Firma selbst an ihre Kunden
  stellt. Landet unter `.../<Jahr>/Ausgang/<Monat>/`.

Je nachdem, was du reinlegst, in den passenden Unterordner einsortieren. Der
Connector unterscheidet nicht nach Dateityp — auch eine CSV-Datei landet
korrekt im Ordnerbaum (ohne OCR, da nicht nötig, siehe unten).

**Ausgangsrechnungen aus der eigenen Software:** Die selbst gebaute
Rechnungssoftware (GitHub + Vercel) kann Rechnungen bisher nur als CSV
exportieren (reine Tabellenwerte, keine PDF-Dokumente) — das reicht dem
Steuerberater aber aus. Export bleibt vorerst manuell: CSV exportieren, Datei
in `./data/dropzone/ausgang/` legen, fertig. Eine Automatisierung (z.B. ein
Vercel-Cron-Job, der die CSV automatisch dorthin liefert) wäre technisch
möglich, würde aber Änderungen im anderen Repo brauchen — aktuell bewusst
zurückgestellt.

Syncthing läuft als Teil dieses Docker-Compose-Stacks (Service `syncthing`)
und synct direkt zwischen deinem Handy und diesen Ordnern — keine
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
3. Die Ordner **"eingang"** und **"ausgang"** existieren in Syncthing nicht
   automatisch (nur ein "Default Folder" ist vorbelegt — den könnt ihr
   löschen, er wird nicht gebraucht). Beide müssen einmalig manuell angelegt
   werden, über **"Ordner hinzufügen"**:
   - Ordner-Label: `eingang`, Ordnerpfad: `/var/syncthing/dropzone/eingang`
   - Ordner-Label: `ausgang`, Ordnerpfad: `/var/syncthing/dropzone/ausgang`

   (Die Pfade sind die Pfade *im Syncthing-Container*, siehe Volume-Mapping
   in `docker-compose.yml` — nicht mit dem Host-Pfad `DROPZONE_HOST_PATH`
   verwechseln.)
4. Danach den Ordner **"eingang"** für das neu gekoppelte Handy freigeben —
   für die allermeisten (Belege, die ihr empfangen habt). Nur falls ihr auch
   Ausgangsrechnungen vom Handy aus einspielen wollt, zusätzlich den Ordner
   **"ausgang"** freigeben.
5. Auf dem Handy: den freigegebenen Ordner annehmen, als lokalen Zielordner
   z.B. einen eigenen "Belege"-Ordner wählen.

## 3. Scan-App einrichten

Rohe Fotos funktionieren, aber eine echte Scan-App (zuschneiden, Kontrast
erhöhen) verbessert die OCR-Erkennung in Docspell deutlich:
- **iOS**: Notizen-App → Kamera-Symbol → "Dokumente scannen" → als PDF in den
  gekoppelten Syncthing-Ordner exportieren ("In Dateien sichern").
- **Android**: z.B. Google Drive (integrierter Scanner) oder
  [Genius Scan](https://play.google.com/store/apps/details?id=com.thegrizzlylabs.geniusscan.free) —
  Export-Ziel auf den Syncthing-Ordner stellen.

Sobald die Datei im synchten Ordner landet, holt sie Syncthing automatisch auf
die NAS, und der Dropzone-Connector lädt sie von dort (Standard-Prüfintervall
60s) nach Docspell hoch.

## Verhalten des Dropzone-Connectors
- Beide Unterordner (`eingang/`, `ausgang/`) werden unabhängig voneinander
  alle `DROPZONE_POLL_INTERVAL_SECONDS` (Default 60s) geprüft.
- Neue Dateien werden nach Docspell hochgeladen, mit den Tags
  `Manuell`/`Unsortiert`/`Eingang` bzw. `.../Ausgang` (in Docspells UI danach
  normal nachsortieren). Die Einsortierung in den Jahr/Eingang-oder-Ausgang/
  Monat-Ordnerbaum unter `./data/belege-nach-monat` übernimmt separat der
  periodisch laufende `connector-mirror-sync` (Standard-Intervall 30 Min.,
  `MIRROR_SYNC_POLL_INTERVAL_SECONDS` in `.env`) — nach dem tatsächlich von
  Docspell erkannten Beleg-Datum, nicht nach der Datei-mtime. Findet Docspell
  (noch) kein Datum (z.B. bei einer CSV-Ausgangsrechnung ohne erkennbares
  Datumsformat), landet die Datei zunächst unter `ohne-datum/<Eingang oder
  Ausgang>/` — sobald du das Datum in Docspells Oberfläche einträgst,
  verschiebt der nächste Sync-Lauf sie automatisch an die richtige Stelle.
- Nach erfolgreichem Upload wird die Datei innerhalb ihres Unterordners nach
  `verarbeitet/` verschoben (nicht gelöscht), z.B.
  `./data/dropzone/eingang/verarbeitet/`.
- Bei fehlgeschlagenem Upload landet die Datei in `fehlgeschlagen/` (ebenfalls
  je Unterordner) — von dort kannst du sie manuell in Docspells Web-UI
  hochladen oder das Problem beheben und zurück in den jeweiligen
  Eingang-/Ausgang-Ordner legen.

## Ports, die vom Handy erreichbar sein müssen
`22000/tcp+udp` (Sync-Protokoll) und `21027/udp` (lokale Geräte-Erkennung) —
beide sind in `docker-compose.yml` auf die reale Netzwerkschnittstelle der
NAS gemappt (nicht nur `127.0.0.1`), müssen also im selben WLAN/LAN
erreichbar sein. Für Sync von unterwegs (ausserhalb des Heimnetzes) zusätzlich
Port-Weiterleitung am Router oder ein VPN zur NAS einrichten.
