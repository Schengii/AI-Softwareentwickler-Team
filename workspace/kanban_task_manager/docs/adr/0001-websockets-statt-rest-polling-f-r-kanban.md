# WebSockets statt REST-Polling für Kanban-State-Synchronisation

Status: Angenommen

## Kontext

Anforderung: Interaktives Kanban-Board mit Drag-and-Drop und sofortiger UI-Aktualisierung. REST-Polling wäre einfach zu implementieren, führt aber zu hoher Latenz oder unnötiger Serverlast.

## Entscheidung

Einsatz von WebSockets statt REST-Polling für die State-Synchronisation.

## Konsequenzen

Ermöglicht Echtzeit-Synchronisation und sofortige UI-Updates. Höhere Komplexität bei Verbindungsmanagement, State-Synchronisation und Skalierung (Sticky Sessions oder Redis-Pub/Sub erforderlich). Höherer Ressourcenverbrauch auf dem Server.
