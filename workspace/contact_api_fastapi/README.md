# Kontaktliste API

Eine einfache REST-API zur Verwaltung einer persönlichen Kontaktliste, implementiert mit FastAPI.

## Voraussetzungen
- Python 3.9+

## Installation
1. Repository klonen oder Dateien herunterladen.
2. Abhängigkeiten installieren:
   ```bash
   pip install fastapi uvicorn pytest httpx
   ```

## Ausführung
Starte den Server mit:
```bash
uvicorn app.main:app --reload
```
Die API ist anschließend unter `http://127.0.0.1:8000` erreichbar.

## API-Dokumentation
Nach dem Start findest du die interaktive API-Dokumentation (Swagger UI) unter:
`http://127.0.0.1:8000/docs`

## Testing
Führe die Unit-Tests mit `pytest` aus:
```bash
pytest
```

## Changelog

### [1.0.0] - 2023-10-27
- Initiales Release der Kontaktliste API.
- Implementierung der CRUD-Endpunkte (POST, GET, PUT, DELETE).
- In-Memory-Speicher für Kontakte.
- Unit-Tests mit `pytest` und `TestClient` hinzugefügt.
