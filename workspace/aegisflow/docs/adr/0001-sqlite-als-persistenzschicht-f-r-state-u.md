# SQLite als Persistenzschicht für State und Audit-Logs

Status: Angenommen

## Kontext

Das System erfordert echte Datenpersistenz für State-Mutationen, Audit-Logs und Idempotenz-Prüfungen (15-Minuten-Fenster). Eine reine In-Memory-Lösung reicht für produktionsnahe I/O-Heuristiken nicht aus.

## Entscheidung

Wir nutzen SQLite (via aiosqlite und SQLAlchemy 2.0) als Persistenzschicht.

## Konsequenzen

Einfaches Setup ohne externe Abhängigkeiten für Entwicklung und Tests. Erfüllt die Anforderung an echte I/O-Spuren. Bei späterer horizontaler Skalierung (Cluster) muss auf PostgreSQL migriert werden, was durch die Nutzung von SQLAlchemy (ORM) abstrahiert und vereinfacht wird.
