# SQLite als primärer Datenspeicher statt Time-Series-DB/PostgreSQL

Status: Angenommen

## Kontext

Speicherung von Monitoren und Ping-Ergebnissen (Latenz, Status). Optionen: SQLite, PostgreSQL, InfluxDB (Time-Series).

## Entscheidung

SQLite mit asynchronem Treiber (aiosqlite oder SQLAlchemy async) wird als primärer Datenspeicher verwendet.

## Konsequenzen

Sehr einfaches Setup, keine Datenbank-Server-Wartung. Bei extrem hohem Schreibvolumen (viele Pings pro Sekunde) könnte SQLite an seine Grenzen stoßen, was durch Batch-Inserts oder WAL-Modus mitigiert werden muss.
