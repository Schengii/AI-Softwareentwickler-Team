# SQLite statt PostgreSQL für lokale Datenhaltung

Status: Angenommen

## Kontext

DevPulse ist ein persönliches Tool zur Erfassung von Entwickler-Aktivitäten. Die Datenhaltung muss lokal, einfach und wartungsarm sein.

## Entscheidung

Wir verwenden SQLite als relationale Datenbank anstelle von PostgreSQL oder MySQL.

## Konsequenzen

Keine separate Datenbank-Infrastruktur nötig, einfache Backups (Datei kopieren). Nicht geeignet für hochgradig parallele Schreibzugriffe oder verteilte Deployments, was für ein persönliches Entwickler-Tool aber nicht erforderlich ist.
