# Hybride Persistenz: SQLite für Historie, In-Memory für Live-Streaming

Status: Angenommen

## Kontext

Die Plattform muss sowohl historische Log-Daten durchsuchbar vorhalten als auch einen Live-Stream in Echtzeit an das Dashboard senden. Ein reiner In-Memory-Ringbuffer würde bei Neustarts Daten verlieren, eine reine DB-Lösung wäre für Live-Streaming zu langsam (Polling nötig).

## Entscheidung

Hybride Persistenz: SQLite via SQLAlchemy für die dauerhafte Speicherung und Historien-Abfrage, kombiniert mit einem In-Memory Pub/Sub-Manager (asyncio.Queue/Set) für das latenzfreie WebSocket-Broadcasting.

## Konsequenzen

SQLite bietet persistente Speicherung und einfache Abfragen (Volltext, Filter), ist aber bei extrem hohem Durchsatz limitiert. Der In-Memory-Broadcaster (Pub/Sub) entkoppelt das langsame Schreiben in die DB vom schnellen Ausliefern an verbundene WebSocket-Clients. Spätere Skalierung auf PostgreSQL/Redis ist durch saubere Repository-Schnittstellen möglich.
