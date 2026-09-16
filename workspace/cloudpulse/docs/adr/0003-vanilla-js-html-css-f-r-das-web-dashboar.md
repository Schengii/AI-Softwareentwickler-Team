# Vanilla JS/HTML/CSS für das Web-Dashboard statt SPA-Framework

Status: Angenommen

## Kontext

Ein responsives Web-Dashboard wird benötigt. Optionen: React/Vue SPA, serverseitiges Rendering (Jinja2) oder Vanilla JS/HTML/CSS (Static Files).

## Entscheidung

Vanilla JS (ES6) mit HTML/CSS, ausgeliefert über FastAPI StaticFiles.

## Konsequenzen

Kein Build-Schritt (Node.js, Webpack) erforderlich. FastAPI liefert die statischen Dateien direkt aus. Das UI muss manuell DOM-Manipulationen durchführen, was bei sehr komplexen UIs unübersichtlich werden kann.
