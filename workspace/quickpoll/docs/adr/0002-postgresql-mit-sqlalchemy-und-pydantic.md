# PostgreSQL mit SQLAlchemy und Pydantic

Status: Angenommen

## Kontext

Datenmodellierung für Umfragen, Fragen und Stimmen. Alternativen: NoSQL (MongoDB) für Flexibilität, aber relationale Integrität ist für Umfragen (Stimmen-Zählung) kritisch.

## Entscheidung

Einsatz von PostgreSQL mit SQLAlchemy (ORM) und Pydantic für die Datenvalidierung.

## Konsequenzen

Starke Typisierung und einfache Serialisierung/Validierung. Erfordert Migrationen bei Schema-Änderungen. PostgreSQL ist robust für relationale Daten.
