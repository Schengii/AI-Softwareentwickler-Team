# PWA Client Architektur: Vanilla Web Components & Service Worker ohne externen Bundler

Status: Angenommen

## Kontext

Für den Mobile-PWA-Client von ecotrack_ai wird eine Lösung für Benutzeroberfläche, Offline-Fähigkeit, i18n und SVG-Visualisierungen benötigt, die im modularen FastAPI-Monolith nativ serviert werden kann. Optionen: Schweres Frontend-Framework (React/Vue per Build-Step) vs. Vanilla HTML5/CSS3/ES6+ mit nativem Service Worker und modularem Komponentenaufbau.

## Entscheidung

Entscheidung für Vanilla HTML5/CSS3/ES6+ PWA mit modularem Service Worker (Cache-First für Assets, Network-First mit Cache-Fallback für Daten), nativem deklarativem SVG-Rendering für Dashboard-Charts, WCAG 2.1 AA barrierefreiem High-Contrast Design und dynamischem DE/EN i18n Store ohne Build-Tools.

## Konsequenzen

Vorteile: Keine externen CDN-Abhängigkeiten (vollständig offlinefähig nach PWA-Cache), schnelle Ladezeiten auf mobilen Endgeräten, 100% Testbarkeit und WCAG 2.1 AA Konformität. Einschränkungen: Charts werden über dynamisches SVG gerendert, was für gängige Dashboard-KPIs optimal und wartbar ist.
