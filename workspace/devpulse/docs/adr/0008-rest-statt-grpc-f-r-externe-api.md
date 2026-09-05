# REST statt gRPC für externe API

Status: Angenommen

## Kontext

Das Frontend (React) kommuniziert über HTTP und benötigt einfache CRUD-Endpunkte. Interne Services nutzen gRPC (ADR-0004). Für externe Clients wäre gRPC unnötig komplex.

## Entscheidung

Verwendung von REST/HTTP für das öffentliche API (FastAPI).

## Konsequenzen

Einfachere Integration im Browser, breitere Tool-Unterstützung. Verzicht auf gRPC-Streaming für externe Clients, aber das ist für das MVP nicht nötig.
