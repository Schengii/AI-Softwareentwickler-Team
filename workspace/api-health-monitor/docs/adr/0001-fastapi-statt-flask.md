# FastAPI statt Flask

Status: Angenommen

## Kontext

Asynchrone Checks & WebSocket benötigen ASGI‑Framework

## Entscheidung

FastAPI gewählt wegen nativer async‑Unterstützung, automatischer OpenAPI‑Generierung und hoher Performance

## Konsequenzen

Erfordert Python 3.11+, Lernkurve für Pydantic, aber langfristig wartbarer
