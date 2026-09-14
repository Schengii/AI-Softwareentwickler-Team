# DSGVO-konforme AuditLogs (PII-Maskierung & Retention Policy)

Status: Angenommen

## Kontext

Governance-Review hat kritische DSGVO-Probleme im AuditLog bemängelt (fehlende PII-Maskierung, fehlende Retention Policy, Klartext-E-Mails als user_id).

## Entscheidung

Implementierung einer PII-Maskierungs-Funktion (`mask_pii`) für das `changes`-JSON und Pseudonymisierung der `user_id` (SHA-256) im `AuditLogRepository`. Einführung eines Hintergrund-Tasks (`retention_policy_task`) in `app/main.py`, der täglich Logs löscht, die älter als 90 Tage sind.

## Konsequenzen

AuditLogs werden DSGVO-konform gespeichert. Alte Logs werden automatisch nach 90 Tagen gelöscht. E-Mail-Adressen in den Logs werden maskiert bzw. pseudonymisiert.
