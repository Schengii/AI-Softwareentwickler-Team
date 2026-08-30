# SQLite für Kanban-Datenmodellierung

Status: Angenommen

## Kontext

Das Projekt benötigt ein Datenbankschema für Kanban-Boards. SQLite wurde gewählt, um schnell lauffähigen Code zu haben.

## Entscheidung

Verwendung von SQLModel mit SQLite für den Prototyp.

## Konsequenzen

SQLite ist ideal für Entwicklung und kleine Setups, bietet aber keine echte parallele Schreib-Performance wie PostgreSQL. Für Produktion sollte auf PostgreSQL migriert werden.
