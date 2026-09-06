# Dropzone-Connector — Setup

Für Belege, die nie digital ankommen: Restaurant-Quittung, Parkschein,
Tankbeleg — mit dem Handy fotografieren, landet automatisch in Docspell.
Genauso der Weg für den **Amazon-Business-Bulk-Export**: das monatliche
ZIP mit Rechnungen (siehe [`connectors/amazon-business/README.md`](../amazon-business/README.md))
einfach hier entpacken statt fotografieren — der Connector unterscheidet
nicht zwischen den Quellen, er lädt einfach jede neue Datei hoch.

## Einrichtung mit Syncthing (empfohlen — kein Cloud-Anbieter dazwischen)

1. [Syncthing](https://syncthing.net/) auf dem Server installieren (oder als
   eigenen Container ergänzen) und auf dem Handy (Android: Syncthing-App,
   iOS: "Möbius Sync").
2. Einen Ordner auf dem Handy (z.B. den Kamera-Ordner oder einen eigenen
   "Belege"-Ordner) mit `./data/dropzone` auf dem Server syncen.
3. In `.env` `DROPZONE_HOST_PATH=./data/dropzone` setzen (Default passt meist
   schon).

## Alternative: Nextcloud

Falls ihr schon eine Nextcloud betreibt: einen Ordner dort per
`davfs2`/Nextcloud-Client auf dem Server mounten und `DROPZONE_HOST_PATH`
darauf zeigen lassen.

## Verhalten
- Neue Dateien werden alle `DROPZONE_POLL_INTERVAL_SECONDS` (Default 60s)
  geprüft und nach Docspell hochgeladen, mit den Tags `Manuell`/`Unsortiert`
  (in Docspells UI danach normal nachsortieren).
- Nach erfolgreichem Upload wird die Datei nach `verarbeitet/` verschoben
  (nicht gelöscht).
- Bei fehlgeschlagenem Upload landet die Datei in `fehlgeschlagen/` — von dort
  kannst du sie manuell in Docspells Web-UI hochladen oder das Problem
  beheben und zurück in den Dropzone-Ordner legen.
