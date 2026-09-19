# PostgreSQL als primäre Datenbank für Persistenz und Deduplizierung

Status: Angenommen

## Kontext

Für die Speicherung von Webhook-Endpoints, Delivery-Logs und Idempotency-Keys wird eine Datenbank benötigt, die strikte Deduplizierung und relationale Integrität unterstützt. Optionen waren PostgreSQL, MongoDB und Redis (als primärer Store).

## Entscheidung

PostgreSQL wird als primäre Datenbank für alle persistenten Daten (Endpoints, Logs, Idempotency-Keys) gewählt. Die Deduplizierung wird über Unique Constraints auf Datenbankebene sichergestellt.

## Konsequenzen

Vereinfacht das Deployment durch Reduktion der Infrastruktur-Abhängigkeiten. Erfordert sorgfältiges Index-Design für die Deduplizierung. Transaktionssicherheit ist gewährleistet.
