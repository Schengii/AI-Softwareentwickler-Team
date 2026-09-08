# JWT-Authentifizierung für MVP

Status: Angenommen

## Kontext

Für den OpsPilot MVP ist eine schnelle, robuste Authentifizierung erforderlich, um geschützte Endpunkte abzusichern. Es wurde ein JWT-basierter Ansatz gewählt.

## Entscheidung

Implementierung eines /api/v1/auth/login Endpunkts mit hartcodierten Credentials (admin/admin) und JWT-Ausstellung. Frontend-seitige Speicherung im LocalStorage.

## Konsequenzen

Einfache, zustandslose Authentifizierung für den MVP. Erfordert zukünftig eine echte Datenbankanbindung für Benutzer. JWT-Speicherung im LocalStorage ist für den MVP akzeptabel, sollte aber für erhöhte Sicherheit (XSS) langfristig überdacht werden (z.B. HttpOnly Cookies).
