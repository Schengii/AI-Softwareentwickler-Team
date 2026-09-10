# Async SQLAlchemy 2.0 mit PostgreSQL/asyncpg & SQLite/aiosqlite für VaultGuard

Status: Angenommen

## Kontext

Für den Secret Management & Leak Prevention Service "VaultGuard" wird eine relationale Datenbank benötigt, die sowohl verschlüsselte Secrets als auch Audit-Logs mit hoher Integrität speichert.

## Entscheidung

Verwendung von PostgreSQL mit asyncpg als primärem async Treiber und SQLAlchemy 2.0 AsyncSession. Für lokale Tests wird SQLite mit aiosqlite und StaticPool verwendet.

## Konsequenzen

Pro: Volle async I/O Kompatibilität mit FastAPI, hohe Performance unter Last, einheitliches Async-Paradigma.
Contra: Bei alembic/Migrationen muss async_engine in env.py korrekt gehandhabt oder synchroner Treiber für offline DDL genutzt werden.
Beachtung: Niemals synchrone SessionMaker/Engines in der Anwendungslogik verwenden.
