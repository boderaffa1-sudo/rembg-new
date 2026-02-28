# rembg-API Railway Deploy Anleitung

## Problem
Railway Container crasht → 503 Fehler → kein Background Removal

## Ursache
1. Alter Code nutzte Flask Dev Server (single-threaded, crasht bei parallelen Requests)
2. Port 8080 war hartcodiert statt Railway's $PORT Variable

## Was geaendert wurde
| Datei | Aenderung |
|-------|-----------|
| requirements.txt | gunicorn>=21.2.0 hinzugefuegt |
| app.py | MAX_CONTENT_LENGTH 25MB + traceback logging |
| Dockerfile | CMD → gunicorn mit $PORT statt 8080 |
| railway.json | startCommand → gunicorn mit $PORT |

## Deploy Schritte (Railway Dashboard)

### 1. Railway Dashboard oeffnen
- https://railway.app/dashboard
- Service "rembg-new" oeffnen

### 2. WICHTIG: Pruefen ob PORT Variable gesetzt ist
- Settings → Variables
- Wenn `PORT` NICHT vorhanden: Hinzufuegen `PORT` = `8080`
- Railway setzt PORT normalerweise automatisch

### 3. Dateien hochladen
Diese 4 Dateien aus `c:\tante youtube\rembg-api\` muessen auf Railway:
- `requirements.txt`
- `app.py`
- `Dockerfile`
- `railway.json`

### 4. Deploy triggern
- "Deploy" Button klicken
- Warten bis Build fertig ist (kann 5-10 Min dauern wegen Model-Downloads)

### 5. Logs pruefen
In den Logs sollte stehen:
```
[INFO] Starting gunicorn 21.2.0
[INFO] Listening at: http://0.0.0.0:XXXX
[INFO] Using worker: gthread
[INFO] Booting worker with pid: X
>>> Pre-loading default model ...
>>> Flask app ready
```

NICHT mehr:
```
WARNING: This is a development server. Do not use it in a production deployment.
```

### 6. Health Check testen
Im Browser: https://rembg-new-production.up.railway.app/health
Sollte zurueckgeben: `{"status":"ok","models_loaded":["birefnet-general"]}`

## Falls es nicht funktioniert
- Logs checken auf Fehlermeldungen
- Restart count pruefen (max 10)
- Memory pruefen: birefnet-general braucht ~1.5 GB RAM
- Falls "gunicorn: command not found": requirements.txt wurde nicht richtig deployed
