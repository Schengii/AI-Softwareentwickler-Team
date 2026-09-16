# In-Process Asyncio Execution Engine mit Active-Task Registry statt Celery/Redis

Status: Angenommen

## Kontext

Für die Ausführung asynchroner Pipeline-Runs und Step-Sequenzen mit Live-Abbruchfähigkeit (Cancel) wird eine Worker-Architektur benötigt. Optionen: 1) Externer Worker (Celery/RQ + Redis/RabbitMQ), 2) In-Process Asyncio Task Engine mit InMemory-Registry für aktive Tasks.

## Entscheidung

In-Process Asyncio Worker Engine mit zentraler Task-Registry (`active_runs: dict[str, asyncio.Task]`). Ermöglicht direktes `task.cancel()` und feingranulares Step-Streaming ohne zusätzliche Middleware.

## Konsequenzen

Vorteile: Keine externen Abhängigkeiten (Redis, RabbitMQ), minimale Latenz, perfekte Eignung für lokale CI/CD. Nachteile: Bei Serverneustart werden aktive Tasks unterbrochen (müssen beim Boot als ABORTED/FAILED markiert werden), Ein-Knoten-Beschränkung.
