# In-Memory Queues statt externer Message Broker

Status: Angenommen

## Kontext

Das System benötigt eine hochperformante, asynchrone Entkopplung zwischen dem Ingestion-Endpunkt und der Aggregations-Logik sowie ein Pub/Sub-System für WebSockets.

## Entscheidung

Verwendung von `asyncio.Queue` für die Ingestion-Entkopplung und eines In-Memory Pub/Sub-Mechanismus (basierend auf `asyncio.Condition` oder Listen von Queues) für das WebSocket-Streaming.

## Konsequenzen

Keine externen Abhängigkeiten (Redis/Kafka) nötig, einfache Bereitstellung. Allerdings nicht horizontal skalierbar über mehrere Instanzen hinweg (Single-Node-Architektur). Bei Neustart gehen nicht persistierte Metriken im Puffer verloren.
