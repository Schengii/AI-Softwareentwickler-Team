# SQLite statt PostgreSQL oder MongoDB

Status: Angenommen

## Kontext

Wahl des Datenbanksystems. Alternativen: PostgreSQL (zu komplex für MVP), MongoDB (unnötiger Overhead).

## Entscheidung

SQLite als primäre Datenbank.

## Konsequenzen

Vorteile: Extrem leichtgewichtig, keine Server-Infrastruktur nötig, ideal für den MVP. Nachteile: Begrenzte Skalierbarkeit bei sehr hohen Schreiblasten im Vergleich zu PostgreSQL.
