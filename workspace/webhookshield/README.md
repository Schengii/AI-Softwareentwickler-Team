# WebhookShield

Ein leichtgewichtiges FastAPI-Projekt zur sicheren Entgegennahme und Validierung von Webhooks.

## Architektur-Entscheidungen
- **Framework:** FastAPI (asynchron, performant)
- **Datenbank:** SQLite mit SQLAlchemy (In-Memory für Tests, lokal für Entwicklung)
- **Validierung:** Pydantic
- **Testing:** pytest + pytest-asyncio + httpx

## Setup
1. `pip install -r requirements.txt`
2. `pytest` zum Ausführen der Testsuite.
