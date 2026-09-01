# FastAPI mit WebSockets für Echtzeit-Kommunikation

Status: Angenommen

## Kontext

Anforderung: Echtzeit-Updates für Umfrageergebnisse. Alternativen: Polling (ineffizient), Server-Sent Events (nur unidirektional), Socket.io (zusätzlicher Overhead).

## Entscheidung

Einsatz von FastAPI mit nativen WebSockets und einem in-memory Pub/Sub-Mechanismus für das MVP.

## Konsequenzen

Ermöglicht bidirektionale Echtzeit-Kommunikation. FastAPI bietet hohe Performance und native WebSocket-Unterstützung. Erfordert jedoch State-Management für verbundene Clients (Pub/Sub).
