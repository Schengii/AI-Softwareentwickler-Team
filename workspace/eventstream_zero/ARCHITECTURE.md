# Architektur-Dokumentation: EventStream-Zero

## 1. Übersicht
EventStream-Zero ist eine hochperformante, verteilte Event-Streaming-Plattform, die auf Python 3.14 mit AsyncIO und FastAPI basiert. Sie bietet strikte Order-Garantie, resilientes Failover und In-Memory Stream Processing.

## 2. Systemdiagramm
```mermaid
C4Context
    title Systemarchitektur EventStream-Zero

    Person(producer, "Producer", "Sendet Telemetrie/Events")
    Person(consumer, "Consumer", "Liest & verarbeitet Events")

    System_Boundary(cluster, "EventStream-Zero Cluster") {
        Container(api_gateway, "API Gateway", "FastAPI / WebSockets", "Nimmt Requests entgegen")
        Container(raft_node, "Raft Consensus", "Python AsyncIO", "Leader Election, Metadata")
        Container(stream_processor, "Stream Processing", "Python", "Windows, Aggregation")
        Container(cg_coordinator, "Consumer Group Coordinator", "Python", "Rebalancing, Offsets")
        ContainerDb(wal_storage, "WAL Storage", "mmap", "Append-Only Log")
    }

    Rel(producer, api_gateway, "Publishes", "JSON/Binary")
    Rel(api_gateway, wal_storage, "Writes", "mmap")
    Rel(api_gateway, raft_node, "Syncs", "gRPC/Internal")
    Rel(consumer, api_gateway, "Subscribes", "WebSockets")
    Rel(cg_coordinator, consumer, "Coordinates", "Heartbeats")
```

## 3. API-Spezifikation (REST)

### Topics
*   `POST /api/v1/topics`: Erstellt ein neues Topic.
*   `POST /api/v1/topics/{topic}/publish`: Publiziert eine Nachricht.
    *   Payload: `{"correlation_id": "uuid", "payload": "..."}`
*   `GET /api/v1/topics/{topic}/messages`: Liest Nachrichten (paginiert).

### WebSockets
*   `/ws/live`: Live-Stream für Consumer.
    *   Protokoll: JSON-Frames mit Offset-Tracking.

## 4. Kernkomponenten
*   **WAL (Write-Ahead-Log):** Nutzt `mmap` für Zero-Copy-Performance. Segmentiertes Speichermodell.
*   **Consumer Groups:** In-Memory Koordination mit automatischem Rebalancing und Heartbeat-Monitoring.
*   **Stream Processing:** Unterstützt Tumbling, Sliding und Session Windows.

## 5. ADR Referenzen
*   [0001-memory-mapped-mmap-append-only-wal-f-r-s.md](docs/adr/0001-memory-mapped-mmap-append-only-wal-f-r-s.md)
*   [0002-integrierter-raft-konsens-statt-externem.md](docs/adr/0002-integrierter-raft-konsens-statt-externem.md)
*   [0003-hybrides-api-design-grpc-core-fastapi-re.md](docs/adr/0003-hybrides-api-design-grpc-core-fastapi-re.md)
