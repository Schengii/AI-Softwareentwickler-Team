# Asynchrone FastAPI-Architektur mit aiosqlite fuer Webhook-Ingestion und Relay

Status: Angenommen

## Kontext

HookSentinel muss eingehende Webhooks mit extrem niedriger Latenz (HTTP 202) entgegennehmen und asynchron dispatchen. Alternativen: Synchrones Flask/Django, Node.js Express, Go Fiber oder Message-Broker (RabbitMQ/Kafka).

## Entscheidung

Verwendung von FastAPI (asynchron) mit SQLAlchemy 2.0 (asyncio) und aiosqlite. Schnelle Ingestion mit In-Memory/Background-Queue bzw. asynchronem Task-Worker, ohne externe Schwergewicht-Broker wie Kafka/RabbitMQ.

## Konsequenzen

Vorteile: Hoher Durchsatz bei Webhook-Ingestion (I/O non-blocking), native OpenAPI-Dokumentation, leichtgewichtige lokale Persistenz via aiosqlite ohne externe Broker-Infrastruktur. Einschränkungen: Single-File SQLite erfordert WAL-Mode für parallele Lese-/Schreibzugriffe; für verteiltes High-Scale-Clustering müsste künftig PostgreSQL/Redis angebunden werden.
