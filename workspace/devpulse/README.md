# DevPulse

DevPulse ist eine eigenständige Web-Anwendung zur Erfassung und Analyse persönlicher Entwickler-Aktivitäten. Das Tool hilft Entwicklern, Fokuszeiten zu tracken, Git-Aktivitäten zu loggen und Fortschritte visuell aufzubereiten.

## 🚀 Features

- **Session- & Task-Tracker:** Fokus-Timer (Pomodoro) mit Projekt- und Tag-Zuweisung.
- **Git-Aktivitäts-Log:** Erfassung von Commits und Branches.
- **Statistik-Dashboard:** Visualisierung der Fokuszeit und Projektaktivität.
- **Daten-Export:** JSON- und CSV-Export aller Aktivitäten.
- **REST-API:** Vollständige Schnittstelle für alle Datenoperationen.

## 🛠 Tech-Stack

- **Backend:** Python 3, FastAPI, SQLAlchemy (Async), SQLite
- **Frontend:** HTML5, Vanilla CSS (Dark Mode, Glassmorphism), Vanilla JS
- **Architektur:** Schichtentrennung (API, Models, Services, Repositories)

## 📦 Installation & Start

1. **Voraussetzungen:** Python 3.10+ installiert.
2. **Abhängigkeiten:**
   ```bash
   pip install -r requirements.txt
   ```
3. **Anwendung starten:**
   ```bash
   uvicorn app.main:app --reload
   ```
4. **Zugriff:** Öffne `http://127.0.0.1:8000` im Browser.

## 🔌 API-Dokumentation

Nach dem Start der Anwendung ist die interaktive API-Dokumentation unter `/docs` (Swagger UI) verfügbar.

### Wichtige Endpunkte:
- `GET /health`: Systemstatus prüfen.
- `GET /api/sessions`: Alle Sessions abrufen.
- `POST /api/sessions`: Neue Session erstellen.
- `GET /api/projects`: Projektliste abrufen.

## 📁 Projektstruktur

```text
app/
├── core/         # Konfiguration & Settings
├── db/           # Datenbank-Setup & Session-Management
├── models/       # SQLAlchemy ORM-Modelle
├── repositories/ # CRUD-Logik
├── main.py       # FastAPI App-Instanz
static/           # Frontend (HTML/CSS/JS)
tests/            # Test-Suite
```

## 📝 Changelog

### [0.1.0] - 2025-05-22
- Initiales Release: MVP-Backend-Struktur, SQLite-Anbindung und Basis-Frontend-Layout.
