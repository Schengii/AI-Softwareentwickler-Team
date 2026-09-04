# PostgreSQL statt MySQL

Status: Angenommen

## Kontext

Persistenzschicht für Zeiterfassungsdaten, Nutzer‑ und Rollen‑Informationen, sowie Auditing. Benötigt relationale Konsistenz und komplexe Abfragen.

## Entscheidung

PostgreSQL wird als primäre Datenbank gewählt.

## Konsequenzen

Starke ACID‑Garantie, reichhaltige SQL‑Features, gute Skalierbarkeit. PostgreSQL unterstützt JSONB für flexible Daten, ideal für zukünftige Erweiterungen wie Webhook‑Payloads.
