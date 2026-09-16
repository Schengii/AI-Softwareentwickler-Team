# SQLite mit SQLAlchemy AsyncIO für Event- und Bucket-Persistenz

Status: Angenommen

## Kontext

EventForge benötigt persistente Speicherung für Buckets, Webhook-Events und Relay-Delivery-Logs. Zur Auswahl standen PostgreSQL, MongoDB und SQLite.

## Entscheidung

Wir setzen auf SQLite mit SQLAlchemy 2.0 (asyncio + aiosqlite + greenlet) und WAL-Modus.

## Konsequenzen

Vorteile: Null-Konfiguration, sofort lauffähig ohne externe DB-Dienste, ideal für lokales Testing und Entwicklung. Einschränkung: SQLite hat Nebenläufigkeitsgrenzen bei Schreibvorgängen (WAL-Modus aktivieren). 'greenlet' und 'aiosqlite' müssen zwingend in requirements.txt aufgeführt sein.
