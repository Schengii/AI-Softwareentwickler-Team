# JWT statt Session-Cookies

Status: Angenommen

## Kontext

Wahl des Authentifizierungs-Mechanismus. Alternative: Session-Cookies.

## Entscheidung

Verwendung von JWT-basierten Authentifizierung.

## Konsequenzen

Stateless, einfache Skalierbarkeit. Erfordert sichere Token-Handhabung (Refresh-Tokens). Alternative: Session-Cookies (anfälliger für CSRF).
