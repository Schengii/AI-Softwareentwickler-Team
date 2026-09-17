# Monolithische Architektur mit Async FastAPI und SQLite

Status: Angenommen

## Kontext

Das System benötigt eine echtzeitfähige API mit Datenbankanbindung. Die Anforderungen verlangen FastAPI und SQLite/SQLAlchemy 2.0.

## Entscheidung

Verwendung einer monolithischen Architektur mit FastAPI (asynchron) und SQLite über SQLAlchemy 2.0 (asyncio).

## Konsequenzen

Einfaches Deployment und Setup. SQLite ist nicht für hochgradig parallele Schreibzugriffe über mehrere Instanzen hinweg geeignet, reicht aber für die geforderte Aufgabenstellung und Single-Node-Betrieb aus. Async SQLAlchemy erfordert 'greenlet' als Abhängigkeit.
