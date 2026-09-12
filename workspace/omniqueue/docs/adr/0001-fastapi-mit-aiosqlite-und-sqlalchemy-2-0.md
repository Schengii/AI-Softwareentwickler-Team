# FastAPI mit aiosqlite und SQLAlchemy 2.0 als asynchrones Event-Gateway

Status: Angenommen

## Kontext

OmniQueue benötigt hohe Durchsatzraten bei Event-Ingestion und Webhook-Dispatching mit relationaler Datenhaltung (Tenants, Events, Audit-Logs). Alternativen: Synchrones Flask/Django, Node.js, MongoDB/NoSQL.

## Entscheidung

FastAPI mit Python asyncio und SQLAlchemy 2.0 AsyncEngine via aiosqlite. Ermöglicht hochperformante Coroutinen für Event-Dispatching und saubere Typisierung via Pydantic v2.

## Konsequenzen

Vorteile: Vollständig asynchrone Non-Blocking I/O Pipeline, null externe Infrastruktur-Abhängigkeiten in Dev/Test, ACID-Garantien über SQLAlchemy 2.0 AsyncSession.
Einschränkungen: SQLite write-concurrency beschränkt auf WAL-Modus; für Multi-Node Deployment ist Wechsel des SQLAlchemy DB-Dialekts auf PostgreSQL vorgesehen.
