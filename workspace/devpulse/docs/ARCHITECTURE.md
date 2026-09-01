# 🏛️ DevPulse - Architecture Overview

## 1. Systemübersicht
DevPulse ist eine hochverfügbare Fullstack-Monitoring-Plattform zur Echtzeit-Überwachung von Microservices, Metriken und Systemressourcen.

### Tech Stack & Kernkomponenten
- **Backend Framework:** FastAPI (Python 3.11+) mit asynchroner DB-Anbindung (`asyncpg` / `SQLAlchemy 2.0`).
- **Datenbank-Layer:** PostgreSQL 15 für Produktion; In-Memory SQLite für automatisierte Tests (`app/core/config.py`).
- **Frontend:** React 18, TypeScript, Native WebSockets mit Fallback (`ADR-0006`).
- **Inter-Service-Kommunikation:** gRPC für High-Throughput Service-Streams (`ADR-0004`).
- **Observability:** Prometheus Exporter (`ADR-0003`) & OpenTelemetry Interop.

## 2. Dokumentierte Architecture Decision Records (ADRs)
- [`ADR-0001`](docs/adr/0001-kubernetes-statt-docker-swarm-f-r-orches.md): Kubernetes für Service-Orchestrierung.
- [`ADR-0002`](docs/adr/0002-go-statt-java-f-r-microservices.md): High-Performance Microservices.
- [`ADR-0003`](docs/adr/0003-prometheus-statt-influxdb-f-r-metriken.md): Prometheus für Metrikerfassung.
- [`ADR-0004`](docs/adr/0004-grpc-statt-rest-f-r-interne-service-apis.md): gRPC für interne Service-APIs.
- [`ADR-0005`](docs/adr/0005-postgresql-und-sqlalchemy-mit-alembic-f.md): PostgreSQL & Async SQLAlchemy.
- [`ADR-0006`](docs/adr/0006-react-context-native-websocket-mit-fallb.md): React Context & Native WebSocket Event-Stream.
