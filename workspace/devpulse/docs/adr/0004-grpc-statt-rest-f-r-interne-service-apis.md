# gRPC statt REST für interne Service‑APIs

Status: Angenommen

## Kontext

Interne Kommunikation zwischen Monitoring‑Collector, Alert‑Engine und Event‑Processor muss performant und versionierbar sein.

## Entscheidung

gRPC

## Konsequenzen

Stark typisierte, effiziente Binärkommunikation, geringere Latenz, automatische Code-Generierung. Erfordert Protobuf-Definitionen, weniger flexibel für externe Clients.
