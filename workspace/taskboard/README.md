# Kanban & Time Tracker

Ein modernes, produktionsreifes Tool zur Aufgabenverwaltung und Zeiterfassung.

## 🚀 Features
- **Kanban-Board:** Intuitive Aufgabenverwaltung.
- **Zeiterfassung:** Präzises Tracking direkt am Task.
- **Modern Stack:** FastAPI (Backend) & React mit Zustand (Frontend).
- **Barrierefrei:** WCAG 2.2 AA konform.

## 🛠 Tech Stack
- **Backend:** Python 3.11+, FastAPI, Pydantic
- **Frontend:** React 18, TypeScript, Tailwind CSS, Zustand
- **Infrastruktur:** Docker, Docker Compose

## 📦 Setup & Installation

### Voraussetzungen
- Docker & Docker Compose

### Entwicklung starten
```bash
# Repository klonen
git clone <repository-url>
cd <project-root>

# Container starten
docker-compose up --build
```

Die Anwendung ist unter `http://localhost:8000` erreichbar.

## 🐳 Docker Deployment
Das Projekt enthält eine `docker-compose.yml` für die einfache Bereitstellung.

```yaml
version: '3.8'
services:
  backend:
    build: ./app
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:password@db:5432/dbname
  frontend:
    build: ./frontend
    ports:
      - "3000:80"
  db:
    image: postgres:15
    environment:
      POSTGRES_USER: user
      POSTGRES_PASSWORD: password
```

## 📚 Dokumentation
- [Architektur-Entscheidungen (ADRs)](docs/adr/README.md)
- [API-Spezifikation](docs/api/openapi.yaml)

## 📝 Changelog

### [0.1.0] - 2024-05-22
- Initiales Release: Projektstruktur, ADRs für Frontend & Performance, Docker-Setup.
