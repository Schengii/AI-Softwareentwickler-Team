# IncidentPilot Entwickler-Dokumentation

Willkommen bei der IncidentPilot API-Dokumentation.

## Architektur-Überblick
IncidentPilot ist eine Uptime-Monitoring-Lösung, bestehend aus einer React-SPA und einer Python-basierten REST-API (SQLAlchemy/PostgreSQL).

## Authentifizierung
Die API verwendet **JWT (JSON Web Tokens)** zur Authentifizierung.
- Alle geschützten Endpunkte erfordern den Header: `Authorization: Bearer <JWT_TOKEN>`
- Token-Erwerb erfolgt über `/auth/login` (Details siehe OpenAPI-Spezifikation).

## API-Spezifikation
Die vollständige API-Definition finden Sie unter `architecture/openapi.yaml`.

### Wichtige Endpunkte
- `/checks`: Verwaltung der Uptime-Monitore.
- `/alerts/configs`: Konfiguration von Benachrichtigungskanälen.
- `/metrics`: Prometheus-kompatible Metriken für Monitoring-Systeme.

## Datenmodell (PostgreSQL)
Das System basiert auf folgenden Entitäten:
1. **User**: Authentifizierte Nutzer mit Rollen (`admin`, `user`).
2. **Check**: Überwachungsaufträge für URLs.
3. **AlertConfig**: Ziele für Benachrichtigungen (Email, Webhook).

## Fehlerbehandlung
Die API nutzt Standard-HTTP-Statuscodes:
- `200/201`: Erfolg.
- `401`: Nicht autorisiert.
- `429`: Rate-Limit überschritten (Client sollte exponentielles Backoff implementieren).
- `500`: Interner Serverfehler.
