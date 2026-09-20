# In-Memory State Management statt externem Cache (Redis)

Status: Angenommen

## Kontext

Das System erfordert einen Circuit-Breaker, eine Idempotenz-Engine, einen Event-Bus und Rate-Limiting. Üblicherweise wird für verteilte Systeme ein externer Store wie Redis genutzt, um State über mehrere Instanzen hinweg zu teilen. Die Anforderung spezifiziert jedoch explizit 'In-Memory'.

## Entscheidung

Verwendung von prozessinternen, asynchronen In-Memory-Datenstrukturen (z.B. Python `dict` mit `asyncio.Lock`) anstelle einer externen Datenbank wie Redis.

## Konsequenzen

Einfaches Deployment ohne externe Abhängigkeiten (kein Redis nötig). Hohe Performance durch direkten Speicherzugriff. Einschränkung: Der State ist flüchtig (Neustart = Datenverlust) und skaliert nicht out-of-the-box über mehrere Prozesse (Gunicorn/Uvicorn Worker) hinweg, sofern keine Shared-Memory-Mechanismen genutzt werden. Für die geforderte In-Memory-Spezifikation ist dies jedoch der korrekte Trade-off.
