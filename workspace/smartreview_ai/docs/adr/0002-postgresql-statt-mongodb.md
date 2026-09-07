# PostgreSQL statt MongoDB

Status: Angenommen

## Kontext

Wahl der Datenbank für Nutzer- und Review-Daten. Alternative: MongoDB.

## Entscheidung

Verwendung von PostgreSQL.

## Konsequenzen

Starke Konsistenz, komplexe Abfragen möglich. Erfordert Migrations-Management (Alembic). Alternative: MongoDB (flexibleres Schema, aber weniger konsistent).
