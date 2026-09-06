# SQLAlchemy 2.0 mit Alembic für das relationale Persistenzmodell

Status: Angenommen

## Kontext

Das Greenfield-Fullstack-Projekt benötigt ein normalisiertes PostgreSQL-Schema für Benutzer und deren Items sowie reproduzierbare Schemaänderungen. Zur Wahl standen SQLAlchemy/Alembic, ein anderes ORM oder handgepflegte SQL-Skripte.

## Entscheidung

SQLAlchemy 2.0 Declarative Mapping wird als einzige Modellquelle verwendet; Alembic verwaltet versionierte Migrationen. Die Laufzeit- und Migrationsverbindung wird aus settings.DATABASE_URL bezogen und nutzt asyncpg für PostgreSQL.

## Konsequenzen

Modelle bleiben testbar und typsicher, Migrationen sind reproduzierbar und Foreign Keys/Indizes werden zentral definiert. Alembic muss bei Modelländerungen aktualisiert werden; lokale Umgebungen benötigen eine gesetzte DATABASE_URL und die PostgreSQL-Treiberabhängigkeiten.
