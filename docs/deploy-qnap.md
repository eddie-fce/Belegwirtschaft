# Deployment auf QNAP TS-435A

Kurzfassung: Läuft grundsätzlich, weil Docspell offiziell ARM64/ARMv7-Images
veröffentlicht (die TS-435A-Baureihe nutzt einen ARM-Prozessor von Annapurna
Labs) — aber mit ~3,76 GB verfügbarem RAM neben dem laufenden QTS ist es eng.
Dieses Dokument beschreibt die Einrichtung und wie mit dem knappen RAM
umgegangen wird.

## 1. Voraussetzungen auf der NAS

1. **Container Station** aus dem App Center installieren, falls noch nicht
   vorhanden.
2. **SSH aktivieren**: Systemsteuerung → Netzwerk & Dateidienste → Telnet/SSH
   → SSH aktivieren.
3. Per SSH einloggen und prüfen, ob `docker`/`docker compose` gefunden werden:
   ```bash
   ssh admin@<nas-ip>
   docker compose version
   ```
   Falls "command not found": Container-Station-Pfade zum `PATH` hinzufügen
   (Pfad kann je nach QTS-Version variieren, `CACHEDEV1_DATA` ggf. anpassen):
   ```bash
   export PATH="/share/CACHEDEV1_DATA/.qpkg/container-station/bin:/share/CACHEDEV1_DATA/.qpkg/container-station/sbin:$PATH"
   ```
   Für Dauerhaftigkeit in `~/.profile` oder `/opt/etc/profile` eintragen.

**Wichtig:** Für dieses Setup per SSH + `docker compose` CLI arbeiten, nicht
über den Container-Station-"Anwendung erstellen"-Dialog — der GUI-Import
unterstützt `build:`-Abschnitte (eigene Dockerfiles, wie sie die Gmail- und
Dropzone-Connectors brauchen) je nach QTS-Version unterschiedlich gut. Die
SSH-CLI verhält sich wie auf jedem normalen Docker-Host.

## 2. Projekt-Verzeichnis

Auf einen QNAP-Shared-Folder legen statt ins Home-Verzeichnis, z.B.:
```bash
mkdir -p /share/Container/belegwirtschaft
cd /share/Container/belegwirtschaft
git clone https://github.com/eddie-fce/Belegwirtschaft.git .
./scripts/setup.sh
```

## 3. RAM-Budget (das eigentliche Thema)

Mit ~3,76 GB gesamt, wovon QTS selbst, Dateidienste, Antivirus etc. bereits
einen Teil belegen, bleibt für den Docker-Stack realistisch **1,5–2,5 GB**.
Docspells eigene Doku empfiehlt für Postgres+Solr+OCR zusammen eigentlich
4 GB — das schaffen wir hier nicht, deshalb sind in `docker-compose.yml`
bewusst knappe `mem_limit`-Werte gesetzt:

| Service                | Limit  | Warum |
|-------------------------|--------|-------|
| db (Postgres)           | 256 MB | Kleine Metadaten-DB, reicht für persönliche/Firmenbelege |
| solr (Volltextsuche)    | 512 MB | `SOLR_HEAP=384m` begrenzt den JVM-Heap explizit |
| docspell-restserver     | 384 MB | Web-UI/API, moderat |
| docspell-joex           | 768 MB | OCR/Textanalyse — braucht am meisten Headroom |
| connector-gmail/-dropzone | 128 MB je | Schlanke Python-Skripte |

Summe: ~2,1 GB — lässt der NAS noch etwas Luft für QTS selbst.

**Das sind Startwerte, keine Garantie.** Beobachten mit:
```bash
docker stats
```
oder im Container-Station-Ressourcenmonitor. Bei OOM-Kills (Container stirbt
wortlos, `docker compose logs <service>` zeigt abrupten Abbruch):

1. Zuerst **`docspell-joex`** erhöhen (OCR ist der hungrigste Teil) — auf
   Kosten von `solr` oder `db`, falls insgesamt nicht mehr Speicher da ist.
2. Falls das nicht reicht: RAM-Upgrade der TS-435A (SO-DIMM-Slot) ist der
   sauberste Fix — deutlich weniger Frickelei als der Stack dauerhaft am
   Limit zu betreiben.
3. Letzte Instanz, falls kein RAM-Upgrade infrage kommt: prüfen, ob Docspell
   auch **ohne Solr** (nur Metadaten-/Tag-Suche, kein Volltext im
   Dokumentinhalt) betrieben werden kann — das würde `solr` komplett
   einsparen. Das ist in dieser Anleitung nicht ausgearbeitet, da es von der
   genauen Docspell-Version abhängt; bei Bedarf gezielt nachfragen.

## 4. Starten

```bash
docker compose up -d --build
```
Der `--build` ist beim ersten Mal wichtig (Gmail-/Dropzone-Connector-Images
werden aus den mitgelieferten Dockerfiles gebaut, nicht von einer Registry
gezogen — das dauert auf der TS-435A-CPU ein paar Minuten, ist aber einmalig).

## 5. Neustart-Verhalten

`restart: unless-stopped` sorgt dafür, dass die Container nach einem
NAS-Neustart automatisch wieder hochkommen — vorausgesetzt, Container Station
selbst ist so eingestellt, dass es beim Systemstart automatisch startet
(Container-Station-Einstellungen prüfen, ist meist Standard).

## 6. Dropzone/Syncthing auf der QNAP

Syncthing ist im QNAP App Center verfügbar (oder als weiterer Container) —
gleiche Einrichtung wie in [`connectors/dropzone/README.md`](../connectors/dropzone/README.md)
beschrieben, nur dass der Zielordner direkt ein QNAP-Shared-Folder ist statt
ein extra gemounteter.
