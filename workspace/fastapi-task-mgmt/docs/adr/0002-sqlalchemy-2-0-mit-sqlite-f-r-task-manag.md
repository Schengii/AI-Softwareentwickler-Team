# SQLAlchemy 2.0 mit SQLite für Task-Management-Persistenz

Status: Angenommen

## Kontext

Für das Task-Management-System wird eine relationale Datenbank benötigt. SQLite wurde als Standard für die Entwicklung gewählt, um die Komplexität zu minimieren, während SQLAlchemy 2.0 die Abstraktion für einen späteren Wechsel zu PostgreSQL bietet.

## Entscheidung

Verwendung von SQLAlchemy 2.0 mit async-Unterstützung und SQLite als Standard-Datenbank (konfigurierbar über USE_SQLITE).

## Konsequenzen

SQLite vereinfacht die lokale Entwicklung und CI/CD, erfordert jedoch bei einem Wechsel zu PostgreSQL für Produktion eine Anpassung der Connection-Strings und ggf. spezifischer Datentypen. Die `get_db` Dependency stellt sicher, dass Sessions korrekt verwaltet werden.
