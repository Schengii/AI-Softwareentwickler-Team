# SQLite FTS5 für Volltextsuche statt externer Suchmaschine

Status: Angenommen

## Kontext

Das System benötigt eine performante Volltextsuche über Code-Snippets, Titel und Tags. Optionen waren Elasticsearch, PostgreSQL mit tsvector oder SQLite mit FTS5. Da das System leichtgewichtig und einfach zu deployen sein soll, scheiden separate Suchmaschinen aus.

## Entscheidung

Verwendung von SQLite mit der FTS5-Erweiterung (Virtual Tables) für die Volltextsuche.

## Konsequenzen

Einfaches Deployment, keine externen DB-Abhängigkeiten. FTS5 erfordert Trigger zur Synchronisation zwischen der Haupttabelle und der virtuellen FTS-Tabelle. Bei sehr hoher Schreiblast könnte SQLite zum Flaschenhals werden (Write-Locks), was für diese Anwendung aber unwahrscheinlich ist.
