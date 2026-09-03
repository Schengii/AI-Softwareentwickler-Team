# SQLite für MVP-Persistenz

Status: Angenommen

## Kontext

Wahl des Persistenz-Backends für Mock-Definitionen und Traffic-Logs. Optionen: SQLite (einfach, dateibasiert) vs. PostgreSQL (robust, skalierbar).

## Entscheidung

Einsatz von SQLite mit SQLAlchemy für das MVP, um Komplexität gering zu halten und schnelle Iterationen zu ermöglichen.

## Konsequenzen

SQLite ist für MVP und lokale Entwicklung ideal, da kein separater Datenbank-Server nötig ist. Bei hoher Last oder verteilten Instanzen müsste auf PostgreSQL migriert werden.
