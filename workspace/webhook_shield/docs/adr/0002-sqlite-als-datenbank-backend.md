# SQLite als Datenbank-Backend

Status: Angenommen

## Kontext

Wahl der Datenbank für Webhook-Logs.

## Entscheidung

Einsatz von SQLite.

## Konsequenzen

Vorteile: Einfach, keine Server-Infrastruktur nötig, für Logging-Zwecke ausreichend. Nachteile: Begrenzte Konkurrenzfähigkeit bei sehr hohen Schreiblasten. Alternative: PostgreSQL (besser für hohe Last, aber komplexer im Setup).
