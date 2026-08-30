# PostgreSQL statt NoSQL für Kanban-Datenhaltung

Status: Angenommen

## Kontext

Das Kanban-Board benötigt eine zuverlässige Speicherung von Aufgaben, deren Status (Spalten) und deren Reihenfolge (Sortierung). Datenintegrität ist kritisch.

## Entscheidung

Einsatz von PostgreSQL statt einer NoSQL-Datenbank (wie MongoDB).

## Konsequenzen

Bietet ACID-Konformität und strikte Schematreue, was für die Verwaltung von Task-Reihenfolgen und Spalten-Zugehörigkeiten essenziell ist. Erfordert Migrationen bei Schemaänderungen. NoSQL wäre flexibler bei unstrukturierten Daten, erschwert aber die Konsistenz bei komplexen Relationen.
