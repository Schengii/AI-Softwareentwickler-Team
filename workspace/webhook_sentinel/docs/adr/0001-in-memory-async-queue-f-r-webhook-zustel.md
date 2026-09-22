# In-Memory Async Queue für Webhook-Zustellung

Status: Angenommen

## Kontext

Das System muss Webhook-Zustell-Tasks in eine asynchrone Queue stellen. Da SQLite als Datenbank vorgegeben ist, soll das System möglichst leichtgewichtig und ohne zusätzliche Infrastruktur-Abhängigkeiten auskommen.

## Entscheidung

Nutzung einer In-Memory `asyncio.Queue` kombiniert mit FastAPI Lifespan-Events für Background-Worker, statt eines externen Message Brokers.

## Konsequenzen

Einfaches Setup ohne externe Abhängigkeiten (kein Redis/RabbitMQ nötig). Bei einem Neustart des Services gehen noch nicht verarbeitete Events in der In-Memory-Queue verloren, sofern sie nicht vorab in der Datenbank als 'pending' persistiert und beim Start neu geladen werden. Skalierung auf mehrere Instanzen erfordert später ggf. einen Wechsel zu Celery/Redis.
