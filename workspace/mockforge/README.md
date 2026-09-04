# MockForge

MockForge ist eine produktionsreife Web-Anwendung zur dynamischen Erstellung von HTTP-Mocks und zur Echtzeit-Inspektion von API-Traffic. Ideal für die Entwicklung und das Testen von Microservices.

## 🚀 Features

- **Dynamisches Mocking**: Erstellen und Verwalten von HTTP-Mocks (Method, Path, Status, Body).
- **Echtzeit-Traffic-Inspektion**: Aufzeichnung und Analyse von Request/Response-Paaren.
- **Dark-Mode UI**: Modernes, responsives Dashboard für eine optimale Entwicklererfahrung.
- **ASGI-Proxy**: Nahtlose Integration durch Middleware-basierte Traffic-Erfassung.

## 🛠️ Installation

### Voraussetzungen
- Python 3.9+
- `pip`

### Einrichtung
1. Repository klonen:
   ```bash
   git clone <repository-url>
   cd mockforge
   ```

2. Abhängigkeiten installieren:
   ```bash
   pip install -r requirements.txt
   ```

3. Anwendung starten:
   ```bash
   uvicorn app.main:app --reload
   ```

## 📖 Nutzung

- **Dashboard**: Öffnen Sie `http://127.0.0.1:8000` im Browser.
- **API-Verwaltung**: Nutzen Sie die `/admin/mocks` Endpunkte zur Konfiguration.
- **Proxy**: Alle Anfragen über den `/proxy/` Endpunkt werden automatisch geloggt und können im Dashboard eingesehen werden.

## 🏗️ Architektur & Technologie

- **Backend**: Python FastAPI
- **Datenbank**: SQLite (siehe `docs/adr/0001-sqlite-f-r-mvp-persistenz.md`)
- **Proxy**: ASGI-Middleware (siehe `docs/adr/0002-asgi-middleware-f-r-traffic-proxy.md`)

## 📝 Changelog

### [0.1.0] - 2023-10-27
- Initiales Release
- Grundgerüst Backend (FastAPI) & Frontend (HTML/CSS)
- Implementierung der Datenmodelle und Middleware-Struktur
