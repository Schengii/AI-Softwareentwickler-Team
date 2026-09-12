# DLQ- und Replay-Strategie mit Exponential Backoff und Circuit Breaker

Status: Angenommen

## Kontext

Zielempfänger von Webhooks können temporär offline sein oder dauerhaft 5xx/4xx Fehler werfen. Es muss ein zuverlässiger Retry- und DLQ-Mechanismus implementiert werden. Alternativen: Sofortiges Verwerfen, Endlos-Retries (Gefahr von DoS auf Empfänger), reine Redis-DLQ.

## Entscheidung

Implementierung einer statusgesteuerten Dead-Letter-Queue in der relationalen Datenbank mit 3 automatischen Exponential-Backoff-Retries (Faktor 2s) und Circuit-Breaker pro Target-Host. Nach 3 Fehlversuchen Zustandswechsel zu 'dlq' mit Ursache (Status, Timeout, TLS-Fehler). Bereitstellung von POST /api/v1/dlq/{event_id}/replay und DELETE /api/v1/dlq/{event_id}.

## Konsequenzen

Vorteile: Hohe Fehlertoleranz, Schutz vor Kaskadenausfällen durch Circuit Breaker, lückenlose Auditierbarkeit und manuelles Wiederholen fehlerhafter Payloads per UI/API. Einschränkungen: Payloads in DLQ können sensiblen Payload-Inhalt enthalten; Bereinigung/Retention-Policy (z.B. DELETE nach Replay oder TTL) zwingend nötig.
