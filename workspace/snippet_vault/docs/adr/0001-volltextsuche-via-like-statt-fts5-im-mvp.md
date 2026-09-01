# Volltextsuche via LIKE statt FTS5 im MVP

Status: Angenommen

## Kontext

Anforderung war SQLite FTS5 für Volltextsuche. SQLite unterstützt dies, erfordert aber ein spezielles Setup der Datenbank-Tabellen.

## Entscheidung

Verwendung von Standard-SQLAlchemy-Modellen mit LIKE-Filter für das MVP, mit der Option auf FTS5-Migration.

## Konsequenzen

SQLite FTS5 ist performant für Volltextsuche, erfordert aber spezifische Tabellen-Konfiguration (Virtual Tables). Für dieses MVP wurde eine Standard-LIKE-Suche implementiert, um die initiale Komplexität zu reduzieren. Eine Migration auf FTS5 ist jederzeit möglich.
