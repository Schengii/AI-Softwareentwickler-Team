# ADR 0004: Realtime-Observability-Stack

## Status
Angenommen

## Kontext
Für das LogiPulse MVP ist eine Realtime-Visualisierung von Observability-Daten erforderlich. Die bisherige Architektur basiert auf REST-Endpunkten, was für Live-Updates ineffizient ist.

## Entscheidung
Wir setzen auf **Redis Pub/Sub** als Event-Bus und **FastAPI WebSockets** für den Push-Datenstrom an das Frontend.

## Konsequenzen
- **Vorteile:** Geringe Latenz, effiziente Echtzeit-Updates, entkoppelte Architektur zwischen Ingestion und Visualisierung.
- **Nachteile:** Zusätzliche Infrastruktur-Komponente (Redis), Handhabung von WebSocket-Verbindungen (State, Timeouts).
