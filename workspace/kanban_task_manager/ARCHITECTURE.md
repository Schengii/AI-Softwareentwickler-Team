# Kanban Backend Architektur

## Tech-Stack
- **Framework:** FastAPI (Python)
- **Datenbank:** PostgreSQL
- **ORM:** SQLModel
- **Kommunikation:** WebSockets (Starlette)

## WebSocket Events
- `task_moved`: Client sendet `{ "type": "task_moved", "taskId": int, "newStatus": str }`.
- `task_updated`: Server broadcastet `{ "type": "task_updated", "taskId": int, "newStatus": str }` an alle verbundenen Clients.

## Persistenz
Änderungen werden synchron in der PostgreSQL-Datenbank mittels SQLModel aktualisiert.
