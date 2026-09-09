# FastAPI statt Django REST Framework

Status: Angenommen

## Kontext

Backend muss asynchron, leichtgewichtig und schnell sein, um viele gleichzeitige WebSocket‑Verbindungen und REST‑Calls zu unterstützen.

## Entscheidung

FastAPI wurde gewählt, weil es native async/await, automatische OpenAPI‑Generierung und hervorragende Performance bietet.

## Konsequenzen

Verzicht auf das umfangreiche ORM von Django; stattdessen SQLAlchemy (async) wird verwendet. Team muss sich mit Pydantic‑Modellen vertraut machen.
