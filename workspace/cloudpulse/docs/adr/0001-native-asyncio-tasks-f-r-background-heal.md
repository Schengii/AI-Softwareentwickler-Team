# Native asyncio-Tasks für Background-Health-Checker statt externer Worker

Status: Angenommen

## Kontext

Das System benötigt einen periodischen Background-Checker für HTTP-Pings. Optionen waren Celery, APScheduler oder native asyncio-Tasks in FastAPI.

## Entscheidung

Native asyncio-Background-Tasks (gestartet im Lifespan-Event von FastAPI) werden genutzt, um die Services asynchron anzupingen.

## Konsequenzen

Keine externen Abhängigkeiten (wie Redis/RabbitMQ) nötig, einfache Deployment-Struktur. Bei sehr vielen Monitoren (1000+) könnte der Event-Loop blockiert werden, für den Scope aber völlig ausreichend.
