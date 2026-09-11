# Standalone Vanilla JS/CSS Dashboard mit Glassmorphism für FastAPI StaticFiles

Status: Angenommen

## Kontext

Anforderung: Standalone Dashboard-SPA unter static/ mit HTML5, Vanilla CSS (Dark-Mode-Glassmorphism), Vanilla JS und Chart.js zur Echtzeit-Visualisierung von Webhook-Events und Metriken.

## Entscheidung

Realisierung als modulare Vanilla JavaScript & CSS SPA unter static/index.html, static/css/style.css und static/js/app.js mit CDN-Einbindung für Chart.js und robustem WebSocket-Client inklusive automatischem Reconnect und REST-Fallback.

## Konsequenzen

Vorteile: Keine Node.js Build-Pipeline für das Frontend nötig; FastAPI serviert die statischen Assets direkt; blitzschnelle Ladezeiten; minimale Abhängigkeiten. Einschränkungen: Für extrem komplexe Komponenten-Strukturen weniger modular als React/Vue, für das Gateway-Dashboard mit Event-Feed, Metriken und Detail-Modals jedoch ideal wartbar und performant.
