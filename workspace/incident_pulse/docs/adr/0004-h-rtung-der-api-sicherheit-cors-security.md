# Härtung der API-Sicherheit (CORS & Security Headers)

Status: Angenommen

## Kontext

Die FastAPI-Anwendung verwendete eine Wildcard-CORS-Konfiguration (`allow_origins=[\"*\"]`), was ein erhebliches Sicherheitsrisiko darstellt. Zudem fehlten grundlegende Security-Header (HSTS, CSP, X-Frame-Options), um clientseitige Angriffe wie XSS oder Clickjacking zu erschweren.

## Entscheidung

1. Einführung von `pydantic-settings` zur Verwaltung von Umgebungsvariablen.
2. Einschränkung von CORS auf eine Whitelist (Standard: localhost), konfigurierbar via `CORS_ORIGINS`.
3. Implementierung einer `SecurityHeadersMiddleware`, die Best-Practice HTTP-Header (HSTS, CSP, X-Frame-Options, X-Content-Type-Options) bei jeder Response setzt.

## Konsequenzen

- CORS-Origins müssen für Produktion explizit in der `.env` als JSON-Array oder via Umgebungsvariable gesetzt werden.
- Frontend-Ressourcen (Scripts, Styles) müssen sich an die CSP halten (aktuell 'unsafe-inline' für Styles/Scripts erlaubt, was für Vanilla-JS SPAs oft nötig ist, aber bei Bedarf weiter gehärtet werden sollte).
- Clickjacking und MIME-Sniffing werden effektiv blockiert.
