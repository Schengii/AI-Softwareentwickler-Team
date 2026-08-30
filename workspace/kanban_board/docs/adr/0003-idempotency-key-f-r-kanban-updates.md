# Idempotency Key für Kanban-Updates

Status: Angenommen

## Kontext

Drag-and-Drop-Events können bei instabilen Verbindungen mehrfach gesendet werden. Wir benötigen eine sichere Methode, um doppelte Status-Updates zu verhindern.

## Entscheidung

Implementierung von X-Idempotency-Key Header bei allen mutierenden Requests.

## Konsequenzen

Erhöht die Zuverlässigkeit bei Netzwerkfehlern während Drag-and-Drop-Operationen. Erfordert clientseitige Generierung von UUIDs.
