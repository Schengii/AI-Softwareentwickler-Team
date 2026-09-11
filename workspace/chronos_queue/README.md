# Chronos Queue Microservice

Ein asynchroner Job-Scheduler- und Task-Queue-Microservice mit integriertem Web-Dashboard.

## Quickstart

1. Installation:
   ```bash
   pip install -r requirements.txt
   ```

2. Starten:
   ```bash
   uvicorn app.main:app --reload
   ```

## API Dokumentation
Die API-Dokumentation ist unter `/docs` (Swagger UI) verfügbar, sobald der Service läuft.

## Architektur
Details zu Architektur-Entscheidungen finden sich im Ordner `docs/adr/`.
