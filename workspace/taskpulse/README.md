# TaskPulse

TaskPulse ist ein leichtgewichtiges, produktionsreifes Monitoring-Dashboard zur Überwachung von Hintergrund-Aufgaben und API-Endpunkten.

## 🏗️ Architektur
Das Projekt folgt einer klaren Trennung zwischen Backend und Frontend:
- **Backend**: [FastAPI](https://fastapi.tiangolo.com/) (Python) mit [SQLAlchemy](https://www.sqlalchemy.org/) für die Datenbankanbindung.
- **Frontend**: Vanilla JavaScript, HTML5 und Tailwind CSS (via CDN).

### Architekturentscheidungen (ADRs)
- [ADR 0001: FastAPI statt Flask für das Backend](docs/adr/0001-fastapi-statt-flask-f-r-das-backend.md)
- [ADR 0002: SQLAlchemy für Datenzugriffsschicht](docs/adr/0002-sqlalchemy-f-r-datenzugriffsschicht.md)

## 🚀 Installation

1. **Repository klonen**
   ```bash
   git clone <repository-url>
   cd taskpulse
   ```

2. **Abhängigkeiten installieren**
   ```bash
   pip install -r requirements.txt
   ```

3. **Anwendung starten**
   ```bash
   uvicorn app.main:app --reload
   ```

Die Anwendung ist anschließend unter `http://127.0.0.1:8000` erreichbar.

## 📖 API Dokumentation
Nach dem Start der Anwendung finden Sie die interaktive API-Dokumentation unter:
- **Swagger UI**: `http://127.0.0.1:8000/docs`
- **ReDoc**: `http://127.0.0.1:8000/redoc`

## 🛠️ Entwicklung
- **Frontend-Assets**: Befinden sich im Ordner `static/`.
- **Backend-Logik**: Befindet sich im Ordner `app/`.

## 📝 Changelog

### [0.1.0] - 2024-05-22
- Initiales Release von TaskPulse.
- Implementierung des FastAPI-Backends mit SQLite/SQLAlchemy.
- Bereitstellung des Dashboards via Vanilla JS und Tailwind CSS.
