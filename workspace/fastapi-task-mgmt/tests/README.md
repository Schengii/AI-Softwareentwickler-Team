# Testplan: Task-Management-System

## 1. Smoke Tests
- `test_smoke_app`: Überprüft, ob der `/tasks/` Endpunkt erreichbar ist (200 OK).

## 2. Integrations-Tests (CRUD)
- `test_create_task`: Validiert das Anlegen eines Tasks via POST.
- `test_read_tasks`: Validiert das Abrufen der Task-Liste via GET.

## 3. E2E-Test-Skelett
- Geplant: WebSocket-Verbindungstest unter `tests/test_ws.py`.

## Ausführung
1. Abhängigkeiten installieren: `pip install -r requirements-dev.txt`
2. Tests ausführen: `pytest --cov=. tests/`
