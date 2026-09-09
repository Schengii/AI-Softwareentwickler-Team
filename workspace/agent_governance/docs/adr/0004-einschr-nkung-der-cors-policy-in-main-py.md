# Einschränkung der CORS-Policy in main.py

Status: Angenommen

## Kontext

Die bisherige CORS-Konfiguration erlaubte alle Origins ('*') bei gleichzeitigem 'allow_credentials=True', was ein Sicherheitsrisiko darstellt.

## Entscheidung

Einschränkung von 'allow_origins' auf eine konfigurierbare Liste (Standard: 'http://localhost:3000') und explizite Definition der erlaubten HTTP-Methoden.

## Konsequenzen

Die CORS-Richtlinie ist nun restriktiver. Entwickler müssen die Umgebungsvariable 'ALLOWED_ORIGINS' korrekt setzen, um Frontend-Zugriffe zu ermöglichen. Dies verhindert CSRF-Risiken durch zu freizügige '*' Konfigurationen.
