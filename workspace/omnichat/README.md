# OmniChat

OmniChat ist eine performante, skalierbare Realtime-Team-Chat- und Collaboration-Plattform, konzipiert als moderne Alternative zu Slack oder Discord.

## 🚀 Features
- **Realtime Messaging:** Sofortige Nachrichtenübermittlung via WebSockets.
- **Channel & DMs:** Strukturierte Kommunikation in Kanälen und privaten Direktnachrichten.
- **Status-Indikatoren:** Live-Feedback zu Verbindungsstatus und ungelesenen Nachrichten.
- **Skalierbare Architektur:** Basierend auf PostgreSQL und Redis Pub/Sub.

## 🏗️ Architektur
Das System setzt auf eine entkoppelte Architektur:
- **Frontend:** React mit WebSocket-Integration.
- **Backend:** Python-basiert mit WebSocket-Unterstützung.
- **Datenhaltung:** PostgreSQL für persistente Daten, Redis für Realtime-Pub/Sub.

Weitere Details finden Sie in unseren Architecture Decision Records (ADRs):
- [ADR 0001: Redis Pub/Sub für WebSocket-Skalierung](docs/adr/0001-redis-pub-sub-f-r-websocket-skalierung.md)
- [ADR 0002: PostgreSQL Schema mit UUIDs und Optimierung](docs/adr/0002-postgresql-schema-mit-uuids-und-optimier.md)

## 🛠️ Setup & Entwicklung

### Voraussetzungen
- Node.js (v18+)
- Python (v3.10+)
- PostgreSQL (v14+)
- Redis

### Installation
1. Repository klonen:
   ```bash
   git clone <repo-url>
   cd omnichat
   ```
2. Backend-Abhängigkeiten installieren:
   ```bash
   pip install -r requirements.txt
   ```
3. Frontend-Abhängigkeiten installieren:
   ```bash
   npm install
   ```

### Datenbank-Migrationen
Initialisieren Sie das Schema mit dem bereitgestellten SQL:
```bash
psql -d <db_name> -f schema.sql
```

### Entwicklung starten
- **Backend:** `python app/main.py`
- **Frontend:** `npm run dev`

## 🔌 API-Dokumentation
Die vollständige API-Spezifikation (REST & WebSocket-Events) finden Sie unter:
`docs/api/openapi.yaml`

## 📝 Changelog
Alle wesentlichen Änderungen an diesem Projekt werden in dieser Datei dokumentiert.

### [0.1.1] - 2025-05-22
- Added missing `requirements.txt` file to enable backend dependency management.

### [0.1.0] - 2023-10-27
- Initiales Release der Frontend-Architektur (WebSocket-Hook, ChatWindow, App-Layout).
- Dokumentation der Architektur-Entscheidungen (ADRs).
- Setup-Anleitung erstellt.
