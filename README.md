# KortexFinance

KortexFinance ist eine lokal laufende Finanzübersicht für private Einnahmen und Ausgaben. Die Anwendung stellt ein übersichtliches Web-Dashboard bereit, speichert die Daten in einer lokalen SQLite-Datenbank und benötigt keine externe Finanz- oder Cloud-Plattform.

Das Projekt ist bewusst schlank aufgebaut: Das Backend verwendet ausschließlich Python-Standardbibliotheken, das Frontend besteht aus HTML, CSS und Vanilla JavaScript. Dadurch kann KortexFinance ohne Node.js, Paketmanager oder Build-Schritt gestartet werden.

> **Status:** Lokale Einzelserver-Anwendung für private Nutzung. Vor einem Betrieb über das Internet sollten insbesondere HTTPS, Zugriffsschutz und die Standardkonfiguration angepasst werden.

## Funktionen

- Persönliches Dashboard mit
  - aktuellem Saldo
  - Einnahmen und Ausgaben
  - Fixkostenübersicht
  - Cashflow-Verlauf
  - Ausgaben nach Kategorie
- Buchungen für Einnahmen und Ausgaben
- Kategorien wie Wohnen, Lebensmittel, Mobilität, Freizeit und Gehalt
- Einmalige und wiederkehrende Buchungen
- Monatliche oder jährliche Wiederholung
- Eigene Konten und Tags
- Suche und Filter nach Beschreibung, Konto und Tag
- Bearbeiten und Löschen von Buchungen
- Benutzerregistrierung und Anmeldung
- Getrennte Daten je Benutzerkonto
- Passwortänderung und vollständige Kontolöschung
- Administrationsbereich für Benutzerkonten
- Passwort-Reset durch Administratoren
- Helles und dunkles Farbschema
- Deutsche und englische Benutzeroberfläche
- Responsive Darstellung für kleinere Bildschirme
- Lokale Speicherung ohne Übertragung an externe Finanzdienste

## Voraussetzungen

- Python 3.10 oder neuer empfohlen
- Ein moderner Webbrowser
- Keine Python-Pakete von Drittanbietern erforderlich
- Keine Node.js-Installation erforderlich

Git und die GitHub CLI werden nur für Versionsverwaltung und Veröffentlichung benötigt, nicht zum Starten der Anwendung.

## Installation und Start

Repository klonen:

```bash
git clone https://github.com/KortexGLXY-Lab/finanzblick.git
cd finanzblick
```

Anwendung starten:

```bash
python3 app.py
```

Danach im Browser öffnen:

```text
http://127.0.0.1:8080
```

Der Server wird mit `Ctrl+C` beendet.

## Konfiguration über Umgebungsvariablen

Die Anwendung kann ohne Konfiguration gestartet werden. Für lokale Anpassungen stehen folgende Umgebungsvariablen zur Verfügung:

| Variable | Standardwert | Bedeutung |
|---|---|---|
| `KORTEX_ROOT` | Projektordner | Verzeichnis für statische Dateien |
| `KORTEX_DB` | `./finanzen.sqlite3` | Pfad zur SQLite-Datenbank |
| `KORTEX_HOST` | `0.0.0.0` | Adresse, auf der der Server lauscht |
| `KORTEX_PORT` | `8080` | TCP-Port des Webservers |

Beispiel für einen rein lokalen Start auf Port 8080:

```bash
KORTEX_HOST=127.0.0.1 KORTEX_PORT=8080 python3 app.py
```

Für einen anderen Datenbankpfad:

```bash
KORTEX_DB=/pfad/zu/finanzen.sqlite3 python3 app.py
```

`KORTEX_HOST=0.0.0.0` macht den Server grundsätzlich über erreichbare Netzwerkschnittstellen verfügbar. Für einen Rechner, auf dem die Anwendung nur lokal verwendet wird, ist `127.0.0.1` die sicherere Einstellung.

## Erster Start und Konto erstellen

Bei einer neuen Installation wird **kein Admin-Konto und kein Standardpasswort** angelegt. Beim ersten Aufruf öffnet KortexFinance direkt den Bereich **Konto erstellen**.

Dort werden eingegeben:

- Benutzername
- Passwort mit mindestens 8 Zeichen
- Passwortbestätigung

Das Konto wird erst angelegt, wenn beide Passwörter übereinstimmen. Nach erfolgreicher Registrierung wird die Sitzung automatisch gestartet und das persönliche Finanzdashboard geöffnet.

Bei späteren Aufrufen erscheint die normale Anmeldung. Über **Noch kein Konto? Jetzt registrieren** können weitere Benutzerkonten angelegt werden. Jeder Benutzer sieht nur seine eigenen Buchungen, Konten und Tags.

Die Administrationsfunktionen bleiben für bereits vorhandene Benutzer mit der Rolle `admin` verfügbar. Neue Installationen erzeugen jedoch bewusst keinen privilegierten Benutzer automatisch.

## Daten und Datenschutz

Die Anwendung speichert die Finanzdaten lokal in:

```text
finanzen.sqlite3
```

Die Datenbank wird beim ersten Start automatisch erzeugt. Sie enthält unter anderem:

- Benutzerkonten
- Passwort-Hashes
- Sitzungen
- Einnahmen und Ausgaben
- Konten und Tags
- Benutzerpräferenzen
- Informationen zu wiederkehrenden Buchungen

Passwörter werden nicht im Klartext gespeichert, sondern mit PBKDF2-HMAC-SHA256 und zufälligem Salt gehasht. Die Finanzdaten werden von der Anwendung nicht an externe Dienste übertragen.

Die lokale Datenbank ist absichtlich in `.gitignore` ausgeschlossen. Zusätzlich werden SQLite-WAL-, SHM- und Journal-Dateien ignoriert. Dadurch wird verhindert, dass lokale Finanzdaten versehentlich in Git-Commits oder im öffentlichen Repository landen.

> Die `.gitignore` schützt nur vor dem Hinzufügen neuer, noch nicht versionierter Dateien. Eine Datenbank, die bereits mit Git getrackt wurde, muss zusätzlich mit `git rm --cached` aus dem Index entfernt werden.

## Architektur

```text
Browser
  │
  ├── index.html     Oberfläche und Seitenstruktur
  ├── style.css      Layout, Farben, Responsive Design
  └── app.js         API-Aufrufe, Rendering, Diagramme und Interaktionen
       │
       ▼
Python-HTTP-Server
  │
  ├── Authentifizierung und Sitzungen
  ├── Benutzer- und Admin-API
  ├── Buchungs- und Filter-API
  ├── Wiederkehrende Buchungen
  └── Auslieferung der statischen Dateien
       │
       ▼
SQLite
  └── finanzen.sqlite3
```

### Backend

`app.py` implementiert einen HTTP-Server mit `ThreadingHTTPServer` und `BaseHTTPRequestHandler`. Die Datenbankverbindung wird über SQLite hergestellt. Beim Start werden Tabellen und fehlende Spalten für bestehende Datenbanken automatisch angelegt beziehungsweise nachgerüstet.

### Frontend

`index.html` enthält die Anwendungsseiten und Formulare. `app.js` lädt Daten über die lokale JSON-API und aktualisiert Dashboard, Tabellen, Fixkostenliste und Diagramme. `style.css` enthält das visuelle Design einschließlich Dark Mode und mobiler Darstellung.

## Wichtige API-Endpunkte

Die API wird vom gleichen Server bereitgestellt wie die Oberfläche.

### Authentifizierung

- `GET /api/auth/status` – prüfen, ob bereits Benutzerkonten vorhanden sind
- `GET /api/me` – aktuelles Benutzerkonto abrufen
- `POST /api/login` – anmelden
- `POST /api/register` – Benutzerkonto mit Passwortbestätigung erstellen
- `POST /api/logout` – Sitzung beenden

### Finanzen

- `GET /api/entries` – eigene Buchungen abrufen
- `POST /api/entries` – Buchung erstellen
- `PUT /api/entries/<id>` – eigene Buchung ändern
- `DELETE /api/entries/<id>` – eigene Buchung löschen
- `GET /api/summary` – Dashboard-Zusammenfassung abrufen
- `GET /api/accounts` – eigene Konten abrufen
- `POST /api/accounts` – Konto anlegen
- `GET /api/tags` – eigene Tags abrufen
- `POST /api/tags` – Tag anlegen

### Konto und Einstellungen

- `GET /api/account` – Kontodaten und Statistiken abrufen
- `DELETE /api/account` – eigenes Konto und zugehörige Daten löschen
- `POST /api/account/password` – Passwort ändern
- `GET /api/preferences` – Sprache und Präferenzen abrufen
- `PUT /api/preferences` – Sprache und Präferenzen speichern

### Administration

- `GET /api/admin/users` – Benutzerliste abrufen
- `POST /api/admin/users` – Benutzer anlegen
- `PUT /api/admin/users/<id>/password` – Benutzerpasswort zurücksetzen
- `DELETE /api/admin/users/<id>` – Benutzerkonto löschen

Die geschützten Endpunkte setzen eine gültige Sitzung voraus. Administrations-Endpunkte erfordern zusätzlich die Rolle `admin`.

## Projektstruktur

```text
finanzblick/
├── app.py                                  # Python-Backend und JSON-API
├── app.js                                  # Frontend-Logik
├── index.html                              # HTML-Oberfläche
├── style.css                               # Design und Responsive Layout
├── README.md                               # Projektdokumentation
├── .gitignore                              # Ausschluss lokaler Daten und Caches
├── assets/
│   ├── kortex-logo.png                     # Aktives Logo
│   ├── Glassy Cyan KF Monogram on Dark Gradient.png
│   └── Glossy Cyan K-F Emblem.png          # zusätzliche Design-Assets
├── finanzen.sqlite3                        # lokale Datenbank, nicht versioniert
```

Alle PNG- und Branding-Dateien liegen gebündelt im Ordner `assets/`. Die aktive Oberfläche verwendet das Logo aus `assets/kortex-logo.png`.

## Versionsverwaltung

Das öffentliche Repository befindet sich unter:

<https://github.com/KortexGLXY-Lab/finanzblick>

Lokale Änderungen prüfen:

```bash
git status
```

Änderungen committen:

```bash
git add .
git commit -m "Beschreibung der Änderung"
```

Zum Repository pushen:

```bash
git push origin main
```

Vor jedem Commit sollte geprüft werden, dass keine Datenbank, keine `.env`-Datei und keine Zugangsdaten im Staging-Bereich liegen:

```bash
git status
 git diff --cached --name-only
```

## Sicherheitshinweise

KortexFinance ist für lokale Nutzung ausgelegt. Für einen öffentlichen oder produktiven Betrieb sind zusätzliche Maßnahmen notwendig:

- Kein voreingestelltes Admin-Konto oder Standardpasswort verwenden
- Benutzerpasswörter mit mindestens 8 Zeichen wählen
- `KORTEX_HOST=127.0.0.1` verwenden, wenn kein Netzwerkzugriff benötigt wird
- Server nicht direkt ohne HTTPS ins Internet stellen
- Zugriff über einen abgesicherten Reverse Proxy bereitstellen
- Regelmäßige Backups der lokalen Datenbank anlegen und verschlüsselt speichern
- Backups niemals in das Git-Repository legen
- Sitzungen und Datenbankzugriffe vor einem Internetbetrieb weiter härten
- CSRF-Schutz und weitere Web-Sicherheitsmaßnahmen ergänzen

## Bekannte Grenzen

- SQLite ist für eine kleine lokale Anwendung geeignet, nicht für hohe gleichzeitige Last.
- Es gibt keinen automatischen Backup- oder Wiederherstellungsmechanismus.
- Der integrierte HTTP-Server ist kein Ersatz für einen produktiven Webserver.
- Die Oberfläche ist auf Deutsch ausgelegt; die englische Übersetzung deckt die vorhandenen UI-Texte ab.
- Jahresbezogene wiederkehrende Buchungen sollten vor produktiver Nutzung fachlich geprüft werden, insbesondere bei der Darstellung als Fixkosten.

## Lizenz

Eine eigene Lizenzdatei ist derzeit nicht enthalten. Die Nutzungs- und Weitergabebedingungen sollten vor einer öffentlichen Weiterverwendung ausdrücklich festgelegt werden.
