# Dynamische CORS-Konfiguration via Umgebungsvariablen

Status: Angenommen

## Kontext

Die CORS-Konfiguration war hartcodiert, was den produktiven Einsatz verhinderte und ein Sicherheitsrisiko darstellte.

## Entscheidung

Die ALLOWED_ORIGINS werden nun über die Pydantic-Settings aus der Umgebungsvariable 'ALLOWED_ORIGINS' geladen und als Liste in der CORSMiddleware verwendet.

## Konsequenzen

Die CORS-Konfiguration ist nun über Umgebungsvariablen steuerbar, was den produktiven Einsatz ermöglicht und Sicherheitsrisiken durch hartcodierte Werte eliminiert. Erfordert das Setzen von ALLOWED_ORIGINS in der .env Datei.
