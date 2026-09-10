# JWT-basierte Authentifizierung und rollenbasierte Autorisierung

Status: Angenommen

## Kontext

Implementierung einer sicheren Authentifizierung und Autorisierung für die API. OAuth2 mit JWT wurde gewählt, da dies der Industriestandard für moderne APIs ist.

## Entscheidung

Verwendung von FastAPI OAuth2PasswordBearer und JWT-Token für Authentifizierung sowie eine Rollen-basierte Middleware (require_role).

## Konsequenzen

Vorteile: Standardisierte JWT-Validierung, einfache Rollenprüfung. Nachteile: Secret-Key muss sicher verwaltet werden (Umgebungsvariablen). Künftige Änderungen: Integration einer echten Benutzerdatenbank statt hartcodierter Rollen.
