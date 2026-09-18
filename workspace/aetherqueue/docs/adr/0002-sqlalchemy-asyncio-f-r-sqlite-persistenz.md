# SQLAlchemy Asyncio für SQLite Persistenz

Status: Angenommen

## Kontext

Die Persistenz erfolgt in SQLite. Wir benötigen eine Lösung zur Verwaltung von Jobs und deren DAG-Abhängigkeiten. Alternativen sind rohes `aiosqlite` oder ein ORM wie SQLAlchemy.

## Entscheidung

Wir nutzen SQLAlchemy 2.0 mit der Asyncio-Erweiterung (`ext.asyncio`) und `aiosqlite`.

## Konsequenzen

Erhöhte Komplexität durch ORM-Overhead, aber deutlich einfachere und sicherere Handhabung von Relationen (DAG-Abhängigkeiten). Erfordert `aiosqlite` als Treiber.
