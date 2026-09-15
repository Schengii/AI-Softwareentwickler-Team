# FastAPI BackgroundTasks statt Celery für asynchrone Retries

Status: Angenommen

## Kontext

Das System erfordert asynchrone Weiterleitung von Webhooks mit exponentiellem Retry. Optionen: 1) Celery + Redis (robust, aber schwergewichtig), 2) ARQ + Redis, 3) FastAPI BackgroundTasks + Asyncio-basierter In-Memory-Worker. Da das System leichtgewichtig sein soll und SQLite nutzt, ist ein externer Broker unerwünscht.

## Entscheidung

Nutzung eines In-Memory Asyncio-Task-Queues (oder BackgroundTasks) in Kombination mit der SQLite-Datenbank als persistenter State-Store für den Retry-Mechanismus.

## Konsequenzen

Kein Redis/RabbitMQ notwendig, was das Deployment extrem vereinfacht (nur ein Container). Bei einem Neustart des Services gehen allerdings noch nicht verarbeitete In-Memory-Retries verloren. Dies wird durch einen Startup-Job kompensiert, der 'pending'/'failed' Events aus der SQLite-Datenbank liest und erneut einreiht.
