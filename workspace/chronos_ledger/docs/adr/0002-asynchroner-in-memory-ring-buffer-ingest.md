# Asynchroner In-Memory Ring-Buffer Ingestion mit Batch-Flush

Status: Angenommen

## Kontext

Hohe Ingestion-Lasten (Spitzenlast bis zu Tausenden Events/s) belasten die relationale Datenbank bei synchronem Write. Optionen: 1) Synchrones Schreiben pro Request, 2) Externe Message-Broker (Kafka/RabbitMQ), 3) Asynchroner In-Memory Ring-Buffer mit asyncio Background-Flush-Worker.

## Entscheidung

Entscheidung für Option 3 für Standalone-Betriebsfähigkeit ohne zwingende externe Cluster-Infrastruktur: asyncio-kompatibler Circular Buffer (Ring-Buffer) mit Batch-Flush-Worker (Timeout oder Batch-Size Schwelle). Optionale DLQ bei Persistierungsfehlern.

## Konsequenzen

Vorteile: Sub-Millisekunden Ingestion-Latenz (HTTP 202 Accepted), Entkopplung von DB-Schreibspitzen, Backpressure-Schutz. Einschränkungen: Bei unsauberem Shutdown ohne Drain-Signal droht Pufferverlust; daher Lifespan Graceful Flush und konfigurierbare Buffer-Größe (RingBuffer mit Überlauf-Schutz).
