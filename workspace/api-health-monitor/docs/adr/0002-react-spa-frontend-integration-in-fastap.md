# React SPA Frontend Integration in FastAPI

Status: Angenommen

## Kontext

Dashboard muss Echtzeit-Anzeigen mit WebSocket, Dark-Mode-Charts und Formularverwaltung für API-Checks bieten.

## Entscheidung

Einbindung eines standalone React 18 Dashboards mit Dark Mode Tailwind-Design und Chart.js Live-Visualisierung, serviert direkt durch FastAPI.

## Konsequenzen

Einfache Bereitstellung über FastAPI StaticFiles ohne getrennten Node-Build-Server-Overhead für Produktion, mit vollständiger React- und Chart.js-Funktionalität.
