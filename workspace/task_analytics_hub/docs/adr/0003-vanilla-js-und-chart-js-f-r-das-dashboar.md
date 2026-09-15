# Vanilla JS und Chart.js für das Dashboard

Status: Angenommen

## Kontext

Ein ansprechendes Dark-Mode-Dashboard mit Chart-Visualisierungen soll erstellt werden, das über FastAPI StaticFiles ausgeliefert wird.

## Entscheidung

Verwendung von Vanilla JS, HTML, CSS (Dark Mode) und Chart.js, um komplexe Build-Schritte zu vermeiden.

## Konsequenzen

Keine Notwendigkeit für Node.js im Build-Prozess des finalen Docker-Images. Schnelle Entwicklung, aber bei wachsender Komplexität eventuell schwerer wartbar als ein komponenten-basiertes Framework.
