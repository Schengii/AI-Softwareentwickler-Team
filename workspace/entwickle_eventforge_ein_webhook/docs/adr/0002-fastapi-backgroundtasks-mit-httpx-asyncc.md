# FastAPI BackgroundTasks mit HTTPX AsyncClient für Async Relay Forwarding

Status: Angenommen

## Kontext

Eingehende Webhooks sollen an eine oder mehrere konfigurierte Target-URLs weitergeleitet werden, ohne den Ingestion-Endpunkt zu blockieren. Zur Wahl standen Celery/Redis, externe Queue oder FastAPI BackgroundTasks mit HTTPX AsyncClient.

## Entscheidung

FastAPI BackgroundTasks kombiniert mit HTTPX AsyncClient für asynchrones, nicht-blockierendes Forwarding mit konfigurierbaren Retry-Versuchen.

## Konsequenzen

Vorteile: Keine externe Message-Queue (Redis/RabbitMQ/Celery) nötig; minimale Latenz beim Webhook-Empfang; Status und Response-Code des Targets werden asynchron in Event-Delivery-Logs festgehalten. Einschränkung: Nicht crash-persistent bei plötzlichem Process-Kill, für Test-/Relay-Gateways jedoch der optimale Balance-Punkt.
