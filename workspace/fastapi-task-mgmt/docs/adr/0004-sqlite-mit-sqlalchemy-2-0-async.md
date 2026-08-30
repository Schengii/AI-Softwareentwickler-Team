# SQLite mit SQLAlchemy 2.0 async

Status: Angenommen

## Kontext

Wahl der Datenbanktechnologie für das Task-Management-System. SQLite wurde gewählt, um schnell starten zu können und die Anforderungen an ein robustes, asynchrones System zu erfüllen.

## Entscheidung

Einsatz von SQLite mit SQLAlchemy 2.0 (async) und aiosqlite.

## Konsequenzen

SQLite ist für Entwicklung und kleine Instanzen ideal. Für Produktion muss auf PostgreSQL migriert werden. Die asynchrone Nutzung mit aiosqlite ist performant.
