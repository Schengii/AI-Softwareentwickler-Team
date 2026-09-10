# ADR-0004: JWT-Authentifizierung und RBAC

## Status
Angenommen

## Kontext
Für den Zugriff auf Audit-Logs ist eine sichere Authentifizierung und Autorisierung erforderlich. Wir verwenden JWT für die Identitätsprüfung und RBAC für die Zugriffskontrolle.

## Entscheidung
- **JWT:** Verwendung von HS256 (vorerst) zur Signierung von Tokens.
- **RBAC:** Implementierung von Scopes: `audit:read`, `audit:write`, `admin`.
- **Integration:** `app/auth.py` wird als zentraler Dienst für Token-Generierung und Validierung genutzt.

## Konsequenzen
- Erhöhte Sicherheit durch granulare Berechtigungen.
- Erfordert Anpassung der API-Endpunkte zur Prüfung der Scopes.
