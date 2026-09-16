# SQLite mit SQLAlchemy 2.0 Async für lokale Persistenz

Status: Angenommen

## Kontext

PipelinePilot ist als entwicklerfreundliche lokale Engine konzipiert. Daten müssen persistent und transaktionssicher abgelegt werden. Optionen: 1) Client-Server RDBMS (PostgreSQL), 2) SQLite synchron, 3) SQLite via SQLAlchemy Async (aiosqlite).

## Entscheidung

SQLite mit SQLAlchemy 2.0 Async (`aiosqlite`) und Write-Ahead Logging (WAL). Leichtgewichtig, dateibasiert, keine externe DB-Installation erforderlich.

## Konsequenzen

Vorteile: Vollständig nicht-blockierende I/O für die FastAPI Event-Loop, konsistente async/await Syntax. Einschränkungen: SQLite Schreib-Concurrency durch WAL-Modus steuern, 'greenlet' und 'aiosqlite' müssen explizit in requirements.txt gelistet sein.
