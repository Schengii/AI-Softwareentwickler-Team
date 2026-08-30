# Python/FastAPI als Tech-Stack für das Kanban-Backend

Status: Angenommen

## Kontext

Das Projekt benötigt ein Backend für ein Kanban-Board mit WebSockets und PostgreSQL-Persistenz. Es wurde noch kein Tech-Stack gewählt.

## Entscheidung

Einsatz von Python mit FastAPI, SQLModel und SQLAlchemy/asyncpg für die PostgreSQL-Anbindung.

## Konsequenzen

Python/FastAPI bietet exzellente native Unterstützung für WebSockets (Starlette) und SQLModel für die PostgreSQL-Anbindung. Es ist performant, typsicher und erfüllt die Anforderungen an ein modernes, event-getriebenes Backend.
