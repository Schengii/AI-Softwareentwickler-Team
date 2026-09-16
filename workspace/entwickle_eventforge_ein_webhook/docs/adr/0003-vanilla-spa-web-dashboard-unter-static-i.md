# Vanilla SPA Web Dashboard unter static/index.html

Status: Angenommen

## Kontext

Das Dashboard soll unter static/ ausgeliefert werden und Buckets verwalten sowie Events inspektieren (formatiertes JSON, Header, Relay-Status). Optionen: React/Vite SPA Build vs. Vanilla JS/HTML5 SPA mit Tailwind CDN direkt in static/index.html.

## Entscheidung

Static Web Dashboard unter static/index.html mit modernem Vanilla JS, Tailwind CSS via CDN und Fetch-API gegen FastAPI REST-Endpunkte.

## Konsequenzen

Vorteile: Keine Node.js Build-Pipeline erforderlich; sofort durch FastAPI StaticFiles mountbar; erfüllt DoD-Prüfung und verhindert Build-Inkompatibilitäten. Tailwind CDN + Vanilla JS für reaktives UI. Einschränkung: Nicht für hochkomplexe Multi-Page Enterprise-Frontends gedacht, aber perfekt für Event-Inspektor und Bucket-Management.
