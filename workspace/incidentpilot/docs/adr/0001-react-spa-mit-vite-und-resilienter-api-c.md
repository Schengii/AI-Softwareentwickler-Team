# React SPA mit Vite und Resilienter API-Client-Schicht

Status: Angenommen

## Kontext

Das Frontend für IncidentPilot erfordert ein Echtzeit-Gefühl beim Monitoring von Uptime-Checks, Incident-Management, Alert-Konfiguration und eine performante öffentliche Status-Seite. Es gab die Optionen (1) Next.js SSR, (2) React Single Page Application (Vite + TypeScript) mit Context API und resilientem Fetch Client.

## Entscheidung

Wir entscheiden uns für eine React SPA mit Vite, TypeScript und einer zentralen API-Client-Layer mit exponentiellem Backoff bei HTTP 429. Vite bietet unübertroffene DX und geringe Bundle-Größen. Context API reicht für die Authentifizierung und Monitor-State-Verwaltung vollkommen aus.

## Konsequenzen

Vorteile: Kein schwerer Redux Boilerplate notwendig, extrem schnelle Ladezeiten durch Vite, hohe Resilienz gegen API-Rate-Limits durch Retry-Middleware im API-Client, nahtloser Wechsel zwischen Mock-Daten (für Standalone Status Page/Demo) und Backend API. Einschränkungen: Bei extrem großen State-Bäumen müsste eventuell auf Zustand/Redux refactored werden.
