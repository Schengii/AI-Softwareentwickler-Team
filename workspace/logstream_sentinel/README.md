# LogStream Sentinel

LogStream Sentinel ist eine hochperformante, entwicklerfreundliche Log-Streaming- und Analyse-Plattform. Sie ermöglicht die Echtzeit-Erfassung von Log-Daten, deren Analyse sowie die automatische Erkennung von Fehler-Spikes.

## 🚀 Features
- **Echtzeit-Ingestion**: Schnelle REST-API zur Log-Aufnahme.
- **Live-Streaming**: WebSockets zur sofortigen Anzeige neuer Logs im Dashboard.
- **Interaktives Dashboard**: Modernes Dark-Mode-UI (Vanilla JS/CSS).
- **Intelligente Analyse**: Automatische Erkennung von Error-Spikes und Incident-Management.
- **Metriken**: Echtzeit-Statistiken zur Log-Rate und Fehlerverteilung.

## 🛠 Installation

Voraussetzungen: Python 3.9+

```bash
# Abhängigkeiten installieren
pip install -r requirements.txt
```

## 🚀 Starten der Anwendung

Die Anwendung wird mit `uvicorn` gestartet:

```bash
uvicorn main:app --reload
```

Das Dashboard ist anschließend unter `http://127.0.0.1:8000` erreichbar.

## 📡 API-Dokumentation

### REST-Endpunkte
- `POST /api/logs`: Log-Eintrag senden.
- `GET /api/logs`: Logs abrufen (Filter: `level`, `service_name`, `search`).
- `GET /api/stats`: Echtzeit-Metriken abrufen.
- `GET /api/incidents`: Liste erkannter Incidents.
- `DELETE /api/logs`: Logs älter als X Stunden bereinigen.

### WebSocket
- `ws://127.0.0.1:8000/ws/live`: Live-Stream für neue Log-Einträge.

## 🧪 Tests

Die Testsuite kann mit `pytest` ausgeführt werden:

```bash
pytest
```

## 📝 Changelog

### [0.1.0] - 2026-09-16
- Initiales Release von LogStream Sentinel.
- Implementierung von Ingestion-API, WebSocket-Streaming und Dashboard.
- Einführung von automatischem Incident-Management.
