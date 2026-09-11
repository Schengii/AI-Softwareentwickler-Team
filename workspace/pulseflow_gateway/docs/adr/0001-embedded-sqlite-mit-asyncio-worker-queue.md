# Embedded SQLite mit asyncio Worker-Queue für Event-Ingestion und Dispatching

Status: Angenommen

## Kontext

Anforderung: Asynchrone Worker-Queue und Event-Speicherung für Event-Gateway mit Persistenz, DLQ und Metriken. Optionen: Externe Redis/RabbitMQ-Infrastruktur vs. Embedded SQLite mit asyncio.Queue.

## Entscheidung

Embedded SQLite (WAL-Modus) kombiniert mit einer asynchronen Priority/Worker-Queue für In-Memory Dispatching und persistenter Speicherung von Events und DLQ.

## Konsequenzen

Ermöglicht Single-Node-Betrieb ohne externe Redis/Broker-Abhängigkeit bei vollem ACID-Schutz, WAL-Modus unterstützt paralleles Lesen/Schreiben. Bei Multi-Node-Skalierung kann nahtlos auf PostgreSQL/Redis gewechselt werden.
