# SQLite und FastAPI Monolith für Document Gateway

Status: Angenommen

## Kontext

Das System benötigt eine Datenbank für Dokumenten-Metadaten und Audit-Logs. Da es sich um ein Gateway handelt, das leichtgewichtig sein soll, stehen SQLite und PostgreSQL zur Auswahl.

## Entscheidung

Wir verwenden SQLite mit asynchronem SQLAlchemy (aiosqlite) im Rahmen einer monolithischen FastAPI-Architektur.

## Konsequenzen

Einfaches Deployment und Setup. SQLite ist nicht für hochparallele Schreibzugriffe über mehrere Instanzen geeignet, reicht aber für dieses Gateway aus. Asynchrones SQLAlchemy erfordert aiosqlite.
