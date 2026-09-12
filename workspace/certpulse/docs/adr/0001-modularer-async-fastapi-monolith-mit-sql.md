# Modularer Async FastAPI Monolith mit SQLite/SQLAlchemy

Status: Angenommen

## Kontext

CertPulse benötigt ein leichtgewichtiges, hochzuverlässiges SSL/TLS- und Domain-Health-Monitoring-System mit Hintergrundprüfungen und REST-API. Es standen Microservices, Serverless und ein modularer Async Monolith zur Auswahl.

## Entscheidung

Entscheidung für einen modularen Async-Monolythen mit FastAPI, Python asyncio für Prüfläufe und SQLite (mit aiosqlite/SQLAlchemy) als Datenbankspeicher.

## Konsequenzen

Geringe Komplexität, einfache Bereitstellung als Einzelprozess (FastAPI + Background Asyncio Worker), SQLite via aiosqlite bietet ausreichend Performance für Domain-Monitoring im mittleren Maßstab (tausende Domains). Späterer Wechsel zu PostgreSQL ohne Code-Änderung über SQLAlchemy ORM möglich.
