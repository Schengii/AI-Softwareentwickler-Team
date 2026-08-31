# SQLite für Check-Historie Persistenz

Status: Angenommen

## Kontext

Persistenz für Check-Historie wird benötigt. SQLite vs PostgreSQL. Da das Tool leichtgewichtig bleiben soll, ist SQLite ideal.

## Entscheidung

Einsatz von SQLite mit SQLAlchemy.

## Konsequenzen

Einfache lokale Dateibasis, keine komplexe DB-Installation nötig. Bei hoher Last oder verteilten Instanzen müsste auf PostgreSQL migriert werden. SQLite-Locking bei Schreibzugriffen beachten.
