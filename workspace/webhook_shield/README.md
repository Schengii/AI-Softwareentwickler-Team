# WebhookShield

WebhookShield ist eine robuste, produktionsreife Web-Anwendung zur sicheren Entgegennahme, Inspektion, Weiterleitung und automatischen Wiederholung von Webhooks.

## 🚀 Features
*   **Sichere Entgegennahme**: Empfang von Webhooks über eine REST-API.
*   **Echtzeit-Monitoring**: Live-Updates der Webhook-Logs via Server-Sent Events (SSE).
*   **Persistenz**: Zuverlässige Speicherung aller Events in einer SQLite-Datenbank.
*   **Modernes UI**: Responsives Dashboard im Dark-Mode.
*   **Container-Ready**: Einfache Bereitstellung mittels Docker.

## 🏗️ Architektur
Das Projekt basiert auf folgenden Architektur-Entscheidungen (ADRs):
*   **[ADR 0001](docs/adr/0001-fastapi-als-web-framework.md)**: FastAPI für performantes, asynchrones Backend.
*   **[ADR 0002](docs/adr/0002-sqlite-als-datenbank-backend.md)**: SQLite für einfache, persistente Datenhaltung.
*   **[ADR 0003](docs/adr/0003-sse-f-r-echtzeit-updates.md)**: SSE für effiziente Echtzeit-Kommunikation zum Frontend.

## 🛠️ Installation & Quickstart

### Voraussetzungen
*   Python 3.9+
*   pip

### Lokale Entwicklung
1. Repository klonen und in das Verzeichnis wechseln.
2. Abhängigkeiten installieren:
   