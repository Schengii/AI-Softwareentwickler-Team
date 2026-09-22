# SQLAlchemy 2.0 für Persistenz

Status: Angenommen

## Kontext

Für die Persistenz von Events und Subscriptions wird SQLite verwendet. Zur Auswahl stehen SQLAlchemy (mit separaten Pydantic-Schemas) oder SQLModel (kombiniert beides).

## Entscheidung

Verwendung von SQLAlchemy 2.0 mit separaten Pydantic v2 Schemas.

## Konsequenzen

Klare Trennung zwischen Datenbankschicht und API-Schicht. Etwas mehr Boilerplate-Code für das Mapping zwischen SQLAlchemy-Modellen und Pydantic-Schemas im Vergleich zu SQLModel, dafür maximale Flexibilität und bewährte Stabilität bei komplexen Queries.
