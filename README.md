# KortexFinance

Lokale Finanzübersicht mit Python 3, SQLite und HTML/CSS/JavaScript.

## Starten

```bash
cd finanzblick
python3 app.py
```

Danach im Browser `http://127.0.0.1:8080` öffnen. Mit `Ctrl+C` wird der Server beendet.

Der automatisch angelegte Administrator meldet sich mit `admin` und dem Startpasswort `admin1234` an. Das Passwort kann anschließend über die Benutzerkonto-Seite geändert werden. In der Benutzerverwaltung können weitere Benutzer angelegt, gelöscht und deren Passwörter zurückgesetzt werden.

Die SQLite-Datei `finanzen.sqlite3` wird beim ersten Start automatisch angelegt. Beim ersten Öffnen kannst du ein Benutzerkonto erstellen. Jeder Benutzer sieht ausschließlich seine eigenen Buchungen. Passwörter werden lokal als PBKDF2-Hash gespeichert; es werden keine Daten an externe Dienste übertragen.
