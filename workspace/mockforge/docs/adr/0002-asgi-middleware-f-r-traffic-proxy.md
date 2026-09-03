# ASGI-Middleware für Traffic-Proxy

Status: Angenommen

## Kontext

Implementierung des Traffic-Proxys. Optionen: Externe Reverse-Proxy-Lösung (Nginx/Traefik) vs. interne ASGI-Middleware in FastAPI.

## Entscheidung

Implementierung als ASGI-Middleware in FastAPI, um eine monolithische, leicht deploybare Anwendung zu erhalten, die direkt auf Mock-Regeln zugreifen kann.

## Konsequenzen

ASGI-Middleware ermöglicht volle Kontrolle über Request/Response-Lifecycle innerhalb des Python-Prozesses. Erfordert sorgfältiges Error-Handling, um die Stabilität der MockForge-Instanz nicht zu gefährden.
