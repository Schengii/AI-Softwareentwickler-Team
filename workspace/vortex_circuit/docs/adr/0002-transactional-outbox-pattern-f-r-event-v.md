# Transactional Outbox Pattern für Event-Versand

Status: Angenommen

## Kontext

Wenn externe Dienste nicht erreichbar sind (Circuit Breaker OPEN), dürfen wichtige Events nicht verloren gehen. Optionen: 1) Direct-Dispatch (Events werden direkt gesendet, bei Fehler verworfen oder im RAM gehalten), 2) Transactional Outbox Pattern (Events werden in derselben DB-Transaktion wie die Geschäftslogik gespeichert und asynchron versendet).

## Entscheidung

Verwendung des Transactional Outbox Patterns mit einer relationalen Datenbank (SQLite/SQLAlchemy). Events werden zunächst in eine Outbox-Tabelle geschrieben. Ein asynchroner Worker liest diese Events und versucht den Versand. Bei Fehlschlägen wird ein adaptiver Backoff angewendet. Nach maximalen Retrys wandern die Events in eine Dead-Letter-Queue (DLQ).

## Konsequenzen

- Erfordert einen Hintergrund-Worker (z.B. via FastAPI BackgroundTasks oder separatem Task-Runner), der die Outbox-Tabelle pollt und Events versendet.
- Erhöht die Datenbanklast durch zusätzliche Schreib- und Leseoperationen.
- Garantiert At-Least-Once Delivery, erfordert Idempotenz auf Empfängerseite.
