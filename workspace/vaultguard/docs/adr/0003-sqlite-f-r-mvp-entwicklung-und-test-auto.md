# SQLite für MVP-Entwicklung und Test-Automatisierung

Status: Angenommen

## Kontext

Das Projekt benötigt eine robuste, aber einfache Datenbank-Lösung für das MVP. PostgreSQL ist als Ziel-Produktionsdatenbank definiert (ADR-0001), für die lokale Entwicklung und das MVP ist SQLite jedoch effizienter und einfacher zu handhaben.

## Entscheidung

Einsatz von SQLite für das MVP unter Verwendung von SQLAlchemy 2.0. Anpassung des Schemas von PostgreSQL-spezifischen Typen auf SQLite-kompatible Typen.

## Konsequenzen

SQLite bietet eine einfache, dateibasierte Entwicklungsumgebung. Die Portierung von PostgreSQL-spezifischen Typen (UUID, JSONB, TIMESTAMPTZ) auf Standard-SQLAlchemy-Typen (String, JSON, DateTime) ermöglicht Kompatibilität, erfordert jedoch im Anwendungscode explizite Konvertierungen (z.B. für UUIDs). Die Performance ist für ein MVP ausreichend, bei hoher Last ist eine Migration auf PostgreSQL (via ADR-0001) vorgesehen.
