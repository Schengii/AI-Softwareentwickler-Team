# PostgreSQL als primärer Datenspeicher

Status: Angenommen

## Kontext

Wahl der primären Datenbank. Alternativen: MongoDB, Elasticsearch.

## Entscheidung

PostgreSQL mit JSONB-Unterstützung bietet den besten Kompromiss aus relationaler Integrität und Flexibilität für Audit-Logs.

## Konsequenzen

ACID-Konformität garantiert Datenintegrität. JSONB-Support erlaubt flexible Log-Strukturen ohne Schema-Migrationen bei jeder Änderung.
