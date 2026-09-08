# Entkoppeltes Vite SPA Frontend mit FastAPI Static Mounting

Status: Angenommen

## Kontext

Das MVP erfordert ein Web-Dashboard mit Dark Mode. Trennung von Frontend-Build und Backend-API erforderlich, aber vereinfachtes Deployment als Container gewollt.

## Entscheidung

Entkoppeltes Vite SPA Frontend, serviert über FastAPI StaticMount in der Produktion.

## Konsequenzen

Frontend-Team baut mit Vite nach `frontend/dist/`. FastAPI mountet `dist/` unter StaticFiles und serviert `index.html` als Single Page Application (SPA) Fallback. Entwicklung kann entkoppelt über Vite Dev Server (mit Proxy) erfolgen, Produktion liefert alles aus einer FastAPI-Instanz.
