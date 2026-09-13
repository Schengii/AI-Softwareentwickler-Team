# Hybrides API-Design: gRPC (Core) & FastAPI (REST/WS)

Status: Angenommen

## Kontext

Clients (Producer/Consumer) und interne Nodes müssen effizient kommunizieren. Reine REST-APIs sind für High-Throughput-Streaming zu langsam. Reines gRPC ist für Web-Clients schwerer zugänglich.

## Entscheidung

Hybrides API-Design: gRPC für interne Raft-Kommunikation und High-Throughput Producer/Consumer. FastAPI (REST & WebSockets) für Management, Monitoring und leichtgewichtige Clients.

## Konsequenzen

Maximale Flexibilität für Clients. gRPC erfordert Protobuf-Kompilierung, bietet aber den höchsten Durchsatz für Node-to-Node und Heavy-Producers. FastAPI bietet einfache Integration für Web-Clients und Monitoring.
