# SQLite statt PostgreSQL für Persistenz

Status: Angenommen

## Kontext

Das System benötigt eine relationale Datenbank zur Speicherung von Workflow-Definitionen, Instanzen und dem Audit-Log. Optionen waren PostgreSQL (hochskalierbar) und SQLite (einfach, dateibasiert).

## Entscheidung

Entscheidung für SQLite als primäre Datenbank, um das Deployment zu vereinfachen und die Anforderungen an die Infrastruktur zu minimieren, da das System primär für abgrenzbare Workflows konzipiert ist.

## Konsequenzen

Einfaches Setup und Deployment, keine externe Datenbank-Infrastruktur nötig. Begrenzte Skalierbarkeit bei sehr vielen gleichzeitigen Schreibzugriffen (Write-Locks), was für die meisten internen Workflow-Systeme jedoch ausreicht. Backup erfolgt durch Dateikopie.
