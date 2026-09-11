# FastAPI + SQLAlchemy Async + SQLite/aiosqlite für Chronos Queue Microservice

Status: Angenommen

## Kontext

Benötigt wird eine leichtgewichtige, performante und asynchrone relationale Speicherung für Jobs und Ausführungshistorien.

## Entscheidung

Verwendung von FastAPI, AsyncSession mit SQLAlchemy 2.0 (asyncio) und SQLite via aiosqlite mit WAL-Modus für Persistenz und Task-Management.

## Konsequenzen

Ermöglicht echt-asynchrones I/O ohne Threading-Blocking für FastAPI und Background-Worker. sqlite+aiosqlite ist leichtgewichtig und erfordert keine externe DB-Infrastruktur.
