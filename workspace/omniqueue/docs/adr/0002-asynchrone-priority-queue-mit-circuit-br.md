# Asynchrone Priority-Queue mit Circuit-Breaker und Ring-Buffer

Status: Angenommen

## Kontext

Für Webhook-Dispatching werden Priorisierung (Prio 1-5), Überlastschutz für Zielsysteme und Resilienz benötigt. Alternativen: Celery mit Redis, RabbitMQ, rein synchrone HTTP-Weiterleitung.

## Entscheidung

Asynchrone In-Memory PriorityQueue (asyncio.PriorityQueue) mit SQLAlchemy Write-Ahead Persistenz, Circuit-Breaker State Machine (Closed/Open/Half-Open) und Ring-Buffer für gleitende Anomalie-Metriken.

## Konsequenzen

Vorteile: Sub-Millisekunden Enqueue/Dequeue Latenz, keine RabbitMQ/Redis Pflicht für Standalone/Edge Deployments, Schirmt fragile Empfänger-Webhooks vor Kaskadenausfällen ab.
Einschränkungen: In-Memory Heap erfordert Persistenz-Sync bei Reboots (Wiederherstellung aus DB). Ring-Buffer hat fixe Memory-Obergrenze.
