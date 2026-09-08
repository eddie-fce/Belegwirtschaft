# Tailscale — Fernzugriff ohne offene Router-Ports

Grund für dieses Setup: SSH-Portforwarding ist auf dieser NAS serverseitig
deaktiviert ("administratively prohibited"), und Docspell/Syncthing sollen
trotzdem von unterwegs (nicht nur im Heim-WLAN) erreichbar sein, ohne Ports
am Router zu öffnen. Tailscale baut dafür ein privates VPN ("Tailnet")
zwischen euren Geräten auf — die NAS läuft dabei als weiterer Container
(Service `tailscale`) mit im Compose-Stack.

**Wie die Verbindung funktioniert:** Der Container leitet zwei Ports als
reines TCP ins Tailnet weiter (`tailscale/serve.json`) — `7880` zu
`docspell-restserver` und `8384` zu `syncthing`, jeweils über den
Docker-internen Servicenamen, unabhängig von `DOCSPELL_BIND_HOST`/
`SYNCTHING_BIND_HOST` in `.env` (die können auf `127.0.0.1` bleiben, siehe
`.env.example`). Bewusst **kein** HTTPS/TLS-Reverse-Proxy (Tailscale Serve im
HTTPS-Modus) — das würde zusätzlich "HTTPS Certificates" im
Tailscale-Adminkonsole voraussetzen. Reines TCP reicht, da die Verbindung
durch WireGuard (Tailscales zugrundeliegendes VPN-Protokoll) ohnehin
verschlüsselt ist.

## 1. Tailscale-Account + eigene Geräte

1. Auf [tailscale.com](https://tailscale.com) kostenlos registrieren (reicht
   für ein privates Tailnet mit wenigen Nutzern/Geräten).
2. Tailscale-App auf den Geräten installieren, von denen aus ihr zugreifen
   wollt (Laptop, Handy — [Downloads](https://tailscale.com/download)) und
   dort einloggen. Diese Geräte sind dann automatisch im selben Tailnet wie
   die NAS.

## 2. Auth-Key erzeugen

In der [Tailscale-Adminkonsole](https://login.tailscale.com/admin/settings/keys):
**Settings → Keys → "Generate auth key"**.
- **Reusable**: an (der Key wird nur beim allerersten Start gebraucht, kann
  aber auch für spätere Neu-Registrierungen nützlich sein).
- **Ephemeral**: **aus** lassen — sonst verschwindet das NAS-Gerät nach jedem
  Container-Neustart wieder aus dem Tailnet und muss neu autorisiert werden.

## 3. Konfiguration

In `.env` (siehe `.env.example`):
```bash
TAILSCALE_AUTHKEY=<der eben erzeugte Key>
TAILSCALE_HOSTNAME=belegwirtschaft
```

## 4. Starten

```bash
docker compose up -d tailscale
sleep 10
docker compose logs --tail=30 tailscale
```

Bei Erfolg taucht das Gerät kurz danach in der
[Tailscale-Adminkonsole](https://login.tailscale.com/admin/machines) unter
dem Namen `TAILSCALE_HOSTNAME` auf. Prüfen, welche Tailscale-IP/MagicDNS-Name
es bekommen hat:
```bash
docker compose exec tailscale tailscale status
```

## 5. Zugriff

Von jedem Gerät im selben Tailnet (egal in welchem Netz es sich gerade
befindet):
- Docspell: `http://<hostname>:7880` (MagicDNS, z.B.
  `http://belegwirtschaft.euer-tailnet.ts.net:7880`) oder
  `http://<tailscale-ip>:7880`
- Syncthing-Weboberfläche: gleiche Adresse mit Port `8384`

Falls MagicDNS nicht automatisch aktiv ist (Tailscale-Adminkonsole →
**DNS** → MagicDNS einschalten), einfach die Tailscale-IP aus Schritt 4
verwenden.

## Sicherheitshinweis

Jedes Gerät im Tailnet kann über diesen Weg auf Docspell **und** Syncthing
zugreifen (Docspells eigener Login schützt zusätzlich, Syncthings
Weboberfläche nur durch das dort gesetzte GUI-Passwort, siehe
`connectors/dropzone/README.md`). Nur Geräte ins Tailnet einladen, denen ihr
vertraut (Benedikt, Edwin) — in der Adminkonsole unter **Users** verwaltbar.
Bei Bedarf lassen sich mit Tailscale-ACLs (Adminkonsole → **Access controls**)
feinere Regeln definieren (z.B. wer welchen Port erreichen darf) — für ein
Zwei-Personen-Tailnet aktuell nicht nötig.

## Troubleshooting

- **Container startet nicht / `tailscale status` zeigt nichts**: Logs
  prüfen (`docker compose logs tailscale`) — meist entweder ein
  ungültiger/abgelaufener Auth-Key, oder `/dev/net/tun` fehlt auf der NAS
  (`ls /dev/net/tun` auf dem Host prüfen; falls nicht vorhanden, TUN-Kernel-
  modul fehlt — in dem Fall `TS_USERSPACE: "true"` in `docker-compose.yml`
  setzen, dann funktioniert `tailscale/serve.json` weiterhin, nur ohne
  eigenes Netzwerkinterface im Container).
- **Ohne Auth-Key gestartet**: einmalig `docker compose logs tailscale` nach
  einem Login-Link (`https://login.tailscale.com/...`) durchsuchen und im
  Browser öffnen, um das Gerät manuell zu autorisieren.
