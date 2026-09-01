# PostgreSQL und SQLAlchemy mit Alembic für Persistenz und USE_SQLITE Fallback

Status: Angenommen

## Kontext

Für DevPulse werden persisistente Daten für Benutzer, Services, Health-Checks und Incidents benötigt. Es muss sowohl Produktion (PostgreSQL) als auch lokale Entwicklungs-/Testumgebungen (SQLite/USE_SQLITE) unterstützt werden.

## Entscheidung

Verwendung von PostgreSQL als primäre Datenbank, SQLAlchemy 2.0 als ORM mit Alembic für Schema-Migrationen und Konfiguration aller DB-Parameter in app/core/config.py inklusive USE_SQLITE Flag.

## Konsequenzen

Vorteile: Typsicheres ORM, flexible Migrationen, einfache lokale Tests ohne externe Abhängigkeiten via USE_SQLITE. Beachtet gelernten Grundsatz mit StaticPool bei In-Memory-SQLite für Unit-Tests.
