# Celery und Redis für asynchrone Webhook-Delivery

Status: Angenommen

## Kontext

Es wird ein asynchroner Worker-Dispatcher mit konfigurierbarem Exponential Backoff und Dead-Letter-Queue für die Webhook-Delivery benötigt. Optionen waren Celery + Redis, ARQ + Redis, RabbitMQ.

## Entscheidung

Celery mit Redis als Message Broker und Result Backend wird für die asynchrone Task-Verarbeitung gewählt. Celery ist der De-facto-Standard in Python, bietet integrierte Retry-Mechanismen und lässt sich gut skalieren.

## Konsequenzen

Erfordert Redis als zusätzliche Infrastruktur-Komponente. Bietet robuste Retry-Mechanismen und Dead-Letter-Queues (DLQ) out-of-the-box. Asynchrone Verarbeitung entkoppelt die Ingestion-API von der Delivery-Logik.
