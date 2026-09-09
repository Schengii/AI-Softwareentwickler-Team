# DevOps- & Agenten-Dashboard (SaaS-MVP)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-05998b.svg)](https://fastapi.tiangolo.com/)
[![React 18](https://img.shields.io/badge/React-18-61dafb.svg)](https://react.dev/)

Das **DevOps- & Agenten-Dashboard** ist eine zentrale Steuerungs- und Überwachungseinheit für verteilte KI-Agententeams. Es bietet Echtzeit-Einblicke in den Agenten-Status, Telemetrie-Daten und ermöglicht die aktive Steuerung von Workflows.

## 🚀 Features (MVP)
- **Live-Monitoring:** Echtzeit-Visualisierung von Agenten-Status (Idle, Running, Error) und Erfolgsquoten.
- **Agent Steering:** Aktive Steuerung (Start/Pause/Abbruch) von Agenten-Tasks.
- **Incident Tracking:** Zentralisiertes Fehler-Management mit Resilienz-Loggings.
- **Sichere API:** JWT-basierte Authentifizierung und CORS-geschützte Endpunkte.

## 🛠️ Architektur
Das System basiert auf einem **FastAPI-Backend** und einer **React/Vite-Frontend-SPA**.

- **Backend:** Python 3.11, FastAPI, Pydantic, SQLAlchemy.
- **Frontend:** React 18, TypeScript, Vite, Tailwind CSS.

## 📦 Installation & Setup

### Voraussetzungen
- Python 3.11+
- Node.js 18+ & npm

### Backend
```bash
# Abhängigkeiten installieren
pip install -r requirements.txt

# Server starten
uvicorn app.main:app --reload
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

## 📝 Changelog

### [0.1.0] - 2024-05-22
- Initiales Release des SaaS-MVP-Grundgerüsts.
- Einrichtung der Projektstruktur (FastAPI + React/Vite).
- Implementierung der grundlegenden Architektur-Entscheidungen (ADRs).

## ⚖️ Architektur-Entscheidungen (ADR)
- [ADR 0001](docs/adr/0001-0001-mvp-scope-und-produktarchitektur-f.md): MVP Scope & Architektur.
- [ADR 0002](docs/adr/0002-fastapi-statt-django-rest-framework.md): FastAPI für hohe Performance.
- [ADR 0003](docs/adr/0003-vite-react-typescript-spa-f-r-frontend-d.md): Vite/React für das Frontend.

---
*Entwickelt für das verteilte KI-Entwicklerteam.*
