# SQLModel statt SQLAlchemy+separate Pydantic-Schemas für ORM-Layer

Status: Angenommen

## Kontext

Für die Datenhaltung (API-Key-Entität) muss zwischen reinem SQLAlchemy+getrennten Pydantic-v2-Schemas oder SQLModel (kombiniert ORM+Pydantic auf Basis von Pydantic v2) gewählt werden. Kriterien: Wartbarkeit, Vermeidung von Code-Duplikation zwischen DB-Modell und API-Schema, Pydantic-v2-Kompatibilität, Reifegrad für Produktionseinsatz.

## Entscheidung

SQLModel (>=0.0.22, basiert auf SQLAlchemy 2.x + Pydantic v2) wird für das persistente Datenmodell (app/models.py, Tabelle ApiKey) verwendet. Für API-Ein-/Ausgabe werden dennoch EIGENSTÄNDIGE Pydantic-v2-Schemas in app/schemas.py definiert (kein direktes Response-Model=SQLModel-Tabelle), um zu verhindern, dass sensible Felder (key_hash, salt) versehentlich über die API exponiert werden. SQLModel liefert damit nur die DB-Table-Definition; die API-Contract-Schemas sind strikt getrennt.

## Konsequenzen

Vorteil: weniger Boilerplate für DB-Modell, native Pydantic-v2-Validierung, einfache Migration zu Alembic später möglich. Nachteil: SQLModel ist weniger reif als reines SQLAlchemy, Alembic-Autogenerate erfordert Sonderimport (sqlmodel.sql.sqltypes). Team-Regel: KEIN SQLModel-Objekt darf direkt als FastAPI response_model dienen - immer Mapping auf schemas.py-Klassen, um Leaks von key_hash/salt zu verhindern.
