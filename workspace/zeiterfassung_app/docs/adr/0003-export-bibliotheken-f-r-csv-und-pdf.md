# Export-Bibliotheken für CSV und PDF

Status: Angenommen

## Kontext

Export-Funktionalität für Zeiteinträge (CSV/PDF) ist erforderlich. CSV ist nativ in Python möglich. Für PDF muss eine Wahl getroffen werden zwischen reportlab (Low-Level, stabil) und weasyprint (HTML-zu-PDF, einfacher, aber schwerere Abhängigkeiten).

## Entscheidung

Nutzung von 'csv' (Standard-Lib) für CSV-Export und 'reportlab' für PDF-Generierung.

## Konsequenzen

Vorteil: Standard-Bibliothek für CSV, keine zusätzlichen Abhängigkeiten. Nachteil: Manuelle PDF-Erstellung ist aufwendig, erfordert zusätzliche Bibliothek. Entscheidung: reportlab für PDF, da es robust und ausgereift ist.
