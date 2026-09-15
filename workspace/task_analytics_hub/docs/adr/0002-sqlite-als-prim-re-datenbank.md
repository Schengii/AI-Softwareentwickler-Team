# SQLite als primäre Datenbank

Status: Angenommen

## Kontext

Das System benötigt eine relationale Datenbank zur Erfassung von Team-Metriken.

## Entscheidung

SQLite wird verwendet, da es leichtgewichtig ist, keine separate Server-Infrastruktur benötigt und für die erwartete Last ausreicht.

## Konsequenzen

Keine Notwendigkeit für einen separaten DB-Container im Docker-Setup. Bei extrem hohem Schreibaufkommen könnte es zu Locking-Problemen kommen, was für dieses Projekt aber unwahrscheinlich ist.
