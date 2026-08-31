# SQLite für lokale Entwicklung mit USE_SQLITE-Flag

Status: Angenommen

## Kontext

Entscheidung zwischen SQLite (einfach, portabel) und PostgreSQL (robust, produktionsreif) für die Entwicklungsumgebung. Gemäß ADR 0002 ist PostgreSQL das Ziel, aber für die initiale Entwicklung ist ein lokales Setup effizienter.

## Entscheidung

Verwendung eines USE_SQLITE-Flags in models.py, um zwischen SQLite (Entwicklung) und PostgreSQL (Produktion) zu wechseln.

## Konsequenzen

Verwendung von SQLite für lokale Entwicklung vereinfacht Setup, erfordert aber bei Umstieg auf PostgreSQL in Produktion Anpassung der Verbindungs-URL. Async-Support durch aiosqlite ist gegeben.
