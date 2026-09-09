# Vite + React + TypeScript SPA für Frontend-Dashboard

Status: Angenommen

## Kontext

Für das DevOps- & Agenten-Dashboard wird eine moderne Single Page Application (SPA) benötigt, die Echtzeit-Telemetrie via WebSockets visualisiert, Agenten-Steuerung erlaubt, Auth-Tokens verwaltet und nahtlos mit dem FastAPI-Backend interagiert.

## Entscheidung

Verwendung von React 18 + TypeScript + Vite + Tailwind CSS + Lucide Icons. Die App verwendet React Context für Auth- und WebSocket-State und React Router (oder Tab/State-basiertes SPA-Routing) für die Navigation.

## Konsequenzen

Gute Typ-Sicherheit durch TypeScript, schnelle Modul-Aggregation und Builds durch Vite, flexibler Live-WebSocket-Sync für Dashboard-Zustände, saubere Trennung im frontend/-Ordner für einfaches StaticFiles-Mounting durch FastAPI.
