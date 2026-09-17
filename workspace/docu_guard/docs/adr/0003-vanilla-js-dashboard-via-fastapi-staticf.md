# Vanilla JS Dashboard via FastAPI StaticFiles

Status: Angenommen

## Kontext

Das System benötigt ein Web-Dashboard unter `public/index.html`. Optionen waren eine separate SPA (React/Vue) mit eigenem Build-Prozess oder eine einfache HTML/JS-Lösung, die direkt vom FastAPI-Backend ausgeliefert wird.

## Entscheidung

Wir verwenden Vanilla HTML/JS/CSS, abgelegt im Ordner `public/`, und liefern diese direkt über FastAPI `StaticFiles` aus.

## Konsequenzen

Kein separater Build-Prozess für das Frontend nötig. Die FastAPI-App muss so konfiguriert werden, dass sie statische Dateien korrekt mit den richtigen MIME-Types (insbesondere für JS) ausliefert. Die UI ist eng an das Backend gekoppelt.
