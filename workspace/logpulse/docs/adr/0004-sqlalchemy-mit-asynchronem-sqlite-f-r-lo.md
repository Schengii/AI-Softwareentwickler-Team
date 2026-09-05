# SQLAlchemy mit asynchronem SQLite für Log-Datenbank

Status: Angenommen

## Kontext

Das Projekt benötigt eine performante, leichtgewichtige Datenbanklösung für Log-Daten. SQLite wurde als Datenbank gewählt. SQLAlchemy dient als ORM für die Modellierung und den Zugriff.

## Entscheidung

Verwendung von SQLAlchemy mit asynchronem SQLite-Treiber (aiosqlite) und expliziter Indexierung der häufig gefilterten Felder. Initialisierung über 'Base.metadata.create_all' (bzw. asynchrones Äquivalent).

## Konsequenzen

Die Verwendung von SQLAlchemy mit aiosqlite ermöglicht asynchrone Datenbankzugriffe in FastAPI. Die Indizierung von 'timestamp', 'level' und 'source' optimiert die Filter-Performance für das Dashboard. Der Verzicht auf ein separates Migrations-Tool wie Alembic ist bei diesem Projektumfang (SQLite, zentrales Modell) für die initiale Phase vertretbar, sollte aber bei Schema-Änderungen überdacht werden.
