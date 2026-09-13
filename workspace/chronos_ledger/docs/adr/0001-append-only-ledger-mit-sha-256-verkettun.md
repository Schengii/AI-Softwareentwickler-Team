# Append-Only Ledger mit SHA-256 Verkettung und Merkle-Tree Verifikation

Status: Angenommen

## Kontext

Revisionssichere Protokollierung verlangt lückenlose Manipulationserkennung. Bisherige Log-Systeme können Daten nachträglich modifizieren. Optionen: 1) Klassische relationale Tabelle mit Update-Triggern, 2) Externe Blockchain, 3) Interne Append-Only SHA-256 Hashverkettung mit periodischen Merkle-Tree Roots.

## Entscheidung

Entscheidung für Option 3: ChronosLedger speichert Audit-Einträge append-only in SQLAlchemy 2.0 (PostgreSQL/SQLite). Jeder Eintrag enthält hash = SHA256(prev_hash + sequence_number + timestamp + tenant_id + payload_hash). Genesis-Block sequence 0 initiiert den Tenant-Ledger. Verifikation erfolgt über lückenlose Rekalibrierung.

## Konsequenzen

Vorteile: Mathematische Manipulationssicherheit, GoBD/DSGVO-Konformität, O(1) Block-Integritätsprüfung, O(log N) Merkle-Proof. Einschränkungen: Append-Only verbietet physische Updates/Löschungen im Ledger (Korrekturen erfolgen via stornierenden Folge-Einträgen / Compensating Events). DB-Rolle erhält nur INSERT/SELECT Rechte.
