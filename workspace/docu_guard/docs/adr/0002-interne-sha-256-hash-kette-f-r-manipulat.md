# Interne SHA-256 Hash-Kette für manipulationssichere Audit-Logs

Status: Angenommen

## Kontext

Das System erfordert eine manipulationssichere (tamper-proof) Audit-Chain für alle Aktionen (Upload, Quarantäne, Freigabe). Optionen waren eine externe Blockchain, eine append-only Datenbank oder eine interne kryptografische Hash-Kette.

## Entscheidung

Wir implementieren eine interne SHA-256 Hash-Kette. Jeder neue Audit-Log-Eintrag hasht seine eigenen Daten zusammen mit dem Hash des vorherigen Eintrags.

## Konsequenzen

Jeder Audit-Eintrag muss sequenziell berechnet werden, da er vom vorherigen Hash abhängt. Dies kann bei extrem hohem Durchsatz zu einem Bottleneck führen, ist aber für die Compliance-Anforderungen zwingend erforderlich.
