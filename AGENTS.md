# Krautl: Projektregeln

## Arbeitskopie und Betrieb

- Lokale Arbeitskopie auf diesem Windows-Host: `C:/Users/info/Documents/Codex/Krautl`. Der im Codex-Projekt gespeicherte Dropbox-Pfad ist veraltet; vor Arbeiten die tatsächliche Arbeitskopie prüfen.
- Maßgebliche Betriebs- und Fachbeschreibung: [README.md](README.md). Vor Änderungen an WhatsApp-Einrichtung, Versand oder Verarbeitung den zugehörigen Abschnitt lesen.
- Die Produktivinstanz läuft unter `https://krautl.erikschweitzer.de`, Server-Arbeitskopie `/opt/app/krautl`. Ein lokaler Build oder Push belegt kein Deployment.
- Bei Server-Aktualisierungsbefehlen das HTTPS-Remote berücksichtigen: `git remote set-url origin https://github.com/erikdreikraut/krautl.git`; kein SSH-Remote voraussetzen.

## WhatsApp

- Gewählter Betrieb: direkte Meta Cloud API, API-only; keine parallele Business-App-Nutzung für die Geschäftsnummer voraussetzen.
- WhatsApp-Nachrichten werden weder initial noch bei weiteren Chatnachrichten KI-klassifiziert. Keine Kategorieauswahl im Chat. KI-Antwortvorschläge bleiben ausdrücklich ausgelöst.
- Keine automatischen Nachrichten oder automatischen Wiederholungen bei unklarem Versand. Revisionen, Reservierungen, Berechtigungen, dauerhafte Versandaufträge und Metas Antwortfenster bei Änderungen erhalten.
- In der Navigation bündelt „Archiv“ die Reiter „WhatsApp-Chats“ und „Gesendete E-Mails“; deren bestehende Such- und Detailfunktionen erhalten.
- Im WhatsApp-Antwortfeld sendet Enter, Strg+Enter fügt einen Zeilenumbruch ein. Beim Öffnen einmalig fokussieren; Polling darf den Fokus nicht aus anderen Feldern stehlen.
