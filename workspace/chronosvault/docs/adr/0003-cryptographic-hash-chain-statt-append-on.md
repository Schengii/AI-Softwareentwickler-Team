# Cryptographic Hash-Chain statt Append-Only DB für Audit Trail

Status: Angenommen

## Kontext

Das System erfordert einen manipulationssicheren Audit-Trail für alle Statusübergänge und Aktionen. Optionen waren eine einfache Append-Only-Tabelle (manipulierbar durch DB-Admins) oder eine kryptografische Hash-Chain (Merkle-Chain-Ansatz).

## Entscheidung

Entscheidung für eine kryptografische Hash-Chain (SHA-256) pro Workflow-Instanz. Jeder Eintrag hasht (Timestamp + Actor + Action + Payload + Previous_Hash).

## Konsequenzen

Jeder Log-Eintrag muss sequenziell berechnet werden (vorheriger Hash wird benötigt). Dies verhindert parallele Schreibvorgänge für denselben Workflow, garantiert aber die kryptografische Unveränderlichkeit. Verifikation kann jederzeit durch Neuberechnung der Kette erfolgen.
