# Containerisierung mit Multi-Stage Build und Non-Root User für pulse_queue

Status: Angenommen

## Kontext

Für den produktionsreifen Betrieb des FastAPI Background-Queue-Services 'pulse_queue' wird ein Container-Image und ein Compose-Setup benötigt. Es muss minimale Imagegröße, Sicherheit (Non-Root User) und saubere SQLite-Datenpersistenz gewährleistet sein.

## Entscheidung

Verwendung eines Multi-Stage Dockerfiles auf Basis von python:3.11-slim mit Non-Root User (appuser, UID 1000), integriertem curl-Healthcheck und Volume-Mounting unter /app/data für SQLite. In docker-compose.yml wird 'restart: unless-stopped' und Healthcheck-Konfiguration standardisiert.

## Konsequenzen

Multi-Stage Build reduziert Angriffsfläche und Image-Größe (keine Build-Tools im Final Image). Durch die Trennung des persistenten Datenverzeichnisses (/app/data) und Ausführung als Non-Root appuser werden Container-Sicherheitsstandards eingehalten. Für Hochverfügbarkeit in verteilten Umgebungen kann die SQLite-URL in docker-compose per Umgebungsvariable durch PostgreSQL ersetzt werden.
