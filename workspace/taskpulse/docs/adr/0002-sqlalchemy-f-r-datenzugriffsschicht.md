# SQLAlchemy für Datenzugriffsschicht

Status: Angenommen

## Kontext

Datenbankzugriffsschicht. Alternativen: Raw SQL, Peewee, SQLAlchemy.

## Entscheidung

SQLAlchemy, da es Industriestandard ist und ORM mit Async-Capabilities bietet.

## Konsequenzen

Erhöhte Typsicherheit, aber zusätzlicher ORM-Overhead.
