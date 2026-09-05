# 🚀 DevPulse - Fullstack Monitoring Platform

[![CI/CD Pipeline](https://github.com/devpulse/devpulse/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/devpulse/devpulse/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0%2B-blue.svg)](https://www.typescriptlang.org/)

DevPulse ist eine produktionsreife Fullstack-Monitoring-Plattform zur Echtzeit-Visualisierung von Systemmetriken, Alerting und Microservice-Gesundheitszuständen.

---

## 🛠 Features

- **Echtzeit-Monitoring:** Live-Status-Updates via WebSockets.
- **Incident Management:** Zentrale Erfassung und Verfolgung von Systemstörungen.
- **Service-Bookmark-Monitor:** Schnelle Übersicht und Lesezeichen-Verwaltung für kritische Infrastruktur-Endpunkte.
- **Dark Mode:** Nahtlose UI-Integration für nächtliche Wartungsfenster.

---

## 🛠 Tech Stack

- **Backend:** Python 3.11+, FastAPI, SQLAlchemy (Async), Pydantic v2, AsyncPG
- **Frontend:** React 18, TypeScript, TailwindCSS, Native WebSockets
- **Metriken & Storage:** PostgreSQL 15, Prometheus Exporter
- **DevOps & Infrastructure:** Docker, Docker Compose, Kubernetes, GitHub Actions

---

## ⚡ Quickstart (Lokale Entwicklung)

### Voraussetzungen
- Python >= 3.11
- Node.js >= 18 & npm
- Docker & Docker Compose

### 1. Installation
```bash
# Backend
pip install -r requirements.txt

# Frontend
npm install
```

### 2. Services starten
```bash
# Startet PostgreSQL und Backend-Worker
docker-compose up -d
# Startet FastAPI-Server
uvicorn app.main:app --reload
# Startet Frontend
npm run dev
```

---

## 📖 API-Referenz

Die API-Dokumentation wird automatisch via OpenAPI generiert. Nach dem Start des Backends finden Sie diese unter:
- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`

### Beispiel: Service-Bookmark abrufen
```bash
curl -X GET "http://localhost:8000/api/v1/services/bookmarks" \
     -H "accept: application/json"
```

---

## 📜 Changelog

### [2026-09-01] - Dokumentations-Update
- README um Service-Bookmark-Monitor Sektion erweitert.
- API-Referenz und Quickstart-Anleitung aktualisiert.
- Struktur für Features und Tech-Stack konsolidiert.

---

## ⚖️ Lizenz
Dieses Projekt steht unter der MIT-Lizenz. Siehe `LICENSE` für weitere Details.
