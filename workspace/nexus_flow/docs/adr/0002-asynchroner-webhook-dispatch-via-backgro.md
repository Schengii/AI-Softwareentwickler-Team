# Asynchroner Webhook-Dispatch via BackgroundTasks und HTTPX

Status: Angenommen

## Kontext

Eingehende Events müssen an Webhook-Subscriber zugestellt werden, ohne die Ingestion-Latenz (HTTP 202/201) zu beeinträchtigen. Option 1: Externe Queue (RabbitMQ/Redis). Option 2: FastAPI BackgroundTasks / asyncio.create_task mit lokaler Delivery-Tabelle.

## Entscheidung

Verwendung von FastAPI BackgroundTasks mit HTTPX (AsyncClient) und Persistierung von Delivery-Attempts in SQLite.

## Konsequenzen

Keine externe Queue-Infrastruktur erforderlich. Bei Serverabstürzen können nicht abgeschlossene Deliveries verloren gehen. Für Produktionsresilienz wird ein Dispatch-Log in SQLite geführt.
