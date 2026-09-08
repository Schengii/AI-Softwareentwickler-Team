# OpsPilot Incident Automation Hub

AI-driven Incident & Workflow Automation Hub.

## 🚀 Features
- **AI-Powered Analysis:** Automatisierte Incident-Klassifizierung und Ursachenanalyse.
- **Resilience-First:** Integrierte Circuit-Breaker für robuste API-Kommunikation.
- **Hybrid Auth:** JWT-basierte Benutzerauthentifizierung kombiniert mit API-Keys für Maschinen-Zugriffe.
- **Modern UI:** Dark-Mode-optimiertes Dashboard mit TailwindCSS.
- **Standard-Konform:** OpenAPI 3.0 Spezifikation für nahtlose Integration.

## 🏗️ Architektur
Das Projekt folgt einer entkoppelten Architektur gemäß den Architecture Decision Records (ADRs):
- **Backend:** FastAPI mit SQLAlchemy 2.0 (Async).
- **Frontend:** Vite SPA mit React und TailwindCSS.
- **Dokumentation:** Alle Design-Entscheidungen sind unter `/docs/adr/` dokumentiert.

## ⚡ Schnellstart

### Voraussetzungen
- Python 3.11+
- Node.js 18+
- Docker & Docker Compose

### Backend
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

## 📚 API-Dokumentation
Die API-Spezifikation ist unter `specs/openapi.yaml` verfügbar. Nach dem Start des Backends ist die interaktive Swagger-UI unter `/docs` erreichbar.

## 🛡️ Sicherheit & Compliance
- **CORS:** Explizite Konfiguration in `app/core/security.py`.
- **Authentifizierung:** JWT & API-Keys (siehe `docs/adr/0002-hybride-jwt-und-api-key-authentifizierun.md`).
- **Resilience:** Circuit-Breaker Muster implementiert (siehe `docs/adr/0003-resilience-guard-mit-async-circuit-break.md`).

## 📝 Changelog
Alle wesentlichen Änderungen werden hier dokumentiert.

### [0.1.0] - 2025-05-15
- Initiales Release: Projektstruktur, ADRs, Basis-Backend & Frontend-Setup.
