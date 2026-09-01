# In-Memory ConnectionManager für WebSockets

Status: Angenommen

## Kontext

Echtzeit-Updates für Umfragen erfordern eine effiziente Verwaltung aktiver Verbindungen. Ein Singleton-ConnectionManager ist für den Start ausreichend.

## Entscheidung

Einsatz eines In-Memory ConnectionManagers für WebSocket-Broadcasts.

## Konsequenzen

Einfache, performante In-Memory-Verwaltung für WebSocket-Broadcasts. Bei horizontaler Skalierung (mehrere Server-Instanzen) muss dies durch Redis Pub/Sub ersetzt werden.
