# SQLAlchemy 2.0 Datenbankschema für OpsPilot

Status: Angenommen

## Kontext

Das Projekt benötigt ein robustes, normalisiertes Datenbankschema für Benutzer, API-Keys, Incidents und Workflows. PostgreSQL wurde als Ziel-Datenbank gewählt.

## Entscheidung

Verwendung von SQLAlchemy 2.0 Style mit `Mapped` und `mapped_column` für Typsicherheit und Performance. PostgreSQL als primäre Datenbank.

## Konsequenzen

Die Verwendung von SQLAlchemy mit einer deklarativen Basis ermöglicht eine einfache Migration auf PostgreSQL. JSON-Felder erlauben Flexibilität bei Incident-Payloads. Indizes auf Status- und Fremdschlüsselfeldern optimieren Abfragen.
