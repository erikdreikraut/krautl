# Krautl: direkter SSH-Betrieb

Am 03.11.2026 erfolgreich von diesem Windows-Host geprüft:

- Alias: `ssh krautl-server`
- Ziel: `root@159.195.122.18`, Port 22, Hostname `krautl-vm-u70403`.
- Eigener Schlüssel: `~/.ssh/krautl_codex` (außerhalb des Repositorys).
- Server-ED25519-Fingerabdruck: `SHA256:P4jwqk7/wnw/qjlkj53lFf9ZMQV5Pj9onsSwMPjNeJY`.
- Fingerabdruck wurde anhand der vom Nutzer gelieferten Serverkonsolen-Ausgabe
  mit der SSH-Antwort verglichen und in `known_hosts` aufgenommen.
- Konfiguration: `IdentitiesOnly yes`, `StrictHostKeyChecking yes`, `BatchMode yes`.
- Öffentlicher Schlüssel serverseitig mit `restrict` in root/authorized_keys.
  Das verhindert Weiterleitungen und PTY, begrenzt aber NICHT die administrativen
  Befehlsrechte. Kein Passwortzugang, kein anderer Schlüssel wurde verändert.

## Verbindungsprüfung

```powershell
ssh krautl-server hostname
```

Keine Hostprüfungen abschalten. Bei geändertem Hostschlüssel abbrechen und über
vertrauenswürdigen Serverzugang erneut prüfen. Private Schlüssel nie ausgeben.

## Deployment-Ablauf für den Agenten

1. Auftrag und Umfang prüfen. GitHub-Status `elestio/deploy` des vorgesehenen
   Commits über den Connector abfragen. Bei pending warten; bei unbekanntem
   Status den Leerlauf separat bestätigen. Serverprozesse auf laufende Builds
   und Compose-Rollouts kontrollieren. Diese Prüfung ist keine atomare Sperre
   gegen einen nachträglich gestarteten Elestio-Lauf; während des manuellen
   Rollouts keine weiteren Pushes/automatischen Rollouts auslösen.
2. Über SSH `/opt/app/krautl`: Git-Stand, lokale Änderungen, Containercode,
   Mounts, Logs prüfen. Keine fremden Dateien entfernen. Ein bereits aktueller
   Container benötigt keinen weiteren Rollout.
3. Für eine tatsächlich benötigte FAQ-Aktualisierung (erst nach Schritt 1):

```powershell
ssh krautl-server 'cd /opt/app/krautl && flock -n /var/lock/krautl-manual-deploy.lock bash -c "git remote set-url origin https://github.com/erikdreikraut/krautl.git && git pull --ff-only origin main && docker compose build app && docker compose --profile jtl-sync up -d --no-deps --force-recreate jtl-sync"'
```

Die lokale Server-Sperre schützt nur kooperierende manuelle Aufrufe, nicht
Elestio. Bei reiner Mount-Änderung und nachgewiesen aktuellem Image entfällt
`docker compose build app`. Andere Dienste, Frontend und Migrationen nur nach
konkretem Änderungsumfang und Projektdokumentation aktualisieren.

4. Logs sofort lesen; Healthcheck getrennt abwarten (60-s-Takt,
   120-s-Anlaufphase). Niemals Erfolg allein aus `Started` ableiten:

```powershell
ssh krautl-server 'cd /opt/app/krautl && docker compose ps jtl-sync && docker compose logs --tail=10 jtl-sync'
```

## Live-Befund am 03.11.2026 nach Zugangseinrichtung

Server-Checkout bereits `fffba1a`; laufender FAQ-Container enthält Shopfilter
und schreibgeschützten Inkasso-Zugangs-Mount. Deshalb kein erneuter Rollout
nötig. Lesende Live-Prüfung bestätigt:

| Artikel | isShopActive | Lokaler Auftrag |
|---|---|---|
| 20560-100 | false | ausgesetzt |
| 20562-100 | false | ausgesetzt |
| 20562-50 | true | nicht ausgesetzt, kein offener Schreibversuch |

Nur 20562-50 liefert weiterhin HTTP 500. Der Dienst ist deshalb weiter unhealthy;
keine vollständige FAQ-Abnahme oder erfolgreiche Elestio-Pipeline behaupten.
Dieser Artikel darf nicht ohne fachliche Klärung deaktiviert/übersprungen werden.
Die bisherige SQL-Diagnose zeigte nVPE=NULL und der API-Stacktrace GetByte/
SqlNullValueException. Keine SQL-Schreibkorrektur durchgeführt.
