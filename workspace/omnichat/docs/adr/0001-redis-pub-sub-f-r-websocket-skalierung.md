# Redis Pub/Sub für WebSocket-Skalierung

Status: Angenommen

## Kontext

Wie synchronisieren wir Nachrichten über mehrere WebSocket-Instanzen hinweg?

## Entscheidung

Redis Pub/Sub als Event-Bus für Realtime-Nachrichten.

## Konsequenzen

Ermöglicht horizontale Skalierung der WebSocket-Server, da Events über Redis zwischen Instanzen synchronisiert werden. Erfordert Redis-Infrastruktur.
