# Vanilla JS SPA statt Frontend-Framework

Status: Angenommen

## Kontext

Für das Frontend des Dashboards standen moderne Frameworks (React, Vue, Angular) oder Vanilla JS zur Auswahl.

## Entscheidung

Wir entscheiden uns für eine Vanilla-JS-SPA (Single Page Application) mit HTML5 und CSS3.

## Konsequenzen

Kein Build-Schritt (Webpack/Vite) zwingend erforderlich, sehr leichtgewichtig, schnelle initiale Ladezeit. Erfordert jedoch manuelles DOM- und State-Management, was bei wachsender Komplexität anspruchsvoll werden kann.
