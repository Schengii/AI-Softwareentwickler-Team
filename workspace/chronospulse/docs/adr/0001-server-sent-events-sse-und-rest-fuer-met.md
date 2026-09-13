# Server-Sent Events (SSE) und REST fuer Metriken-Streaming und Ingestion

Status: Angenommen

## Kontext

ChronosPulse benoetigt performante, asynchrone Endpunkte fuer High-Throughput Metrik-Ingestion und Live-Streaming an Frontend-Dashboards. Zur Auswahl standen WebSockets, gRPC, REST mit Polling und Server-Sent Events (SSE).

## Entscheidung

Entscheidung fuer REST-Ingestion (/api/v1/metrics) und Server-Sent Events (SSE) ueber FastAPI StreamingResponse (/api/v1/metrics/stream). Dies ermoeglicht native Browser-Kompatibilitaet via EventSource ohne zusaetzliche Socket-Libraries und hohe Durchsatzraten.

## Konsequenzen

SSE bietet eine leichtgewichtige, HTTP/2-freundliche Unidirektional-Streaming-Option fuer Dashboards mit minimalem Overhead. Fuer Clients ohne SSE-Support bleibt Standard-REST Ingestion und Polling moeglich. Vollstaendige Pydantic v2 Validierung schuetzt vor fehlerhaften Schemata.
