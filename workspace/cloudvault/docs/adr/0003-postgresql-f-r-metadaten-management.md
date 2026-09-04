# PostgreSQL für Metadaten-Management

Status: Angenommen

## Kontext

Die Anforderung verlangte ein Datenmodell für Users, Files, Tags und Metrics. PostgreSQL wurde gewählt, um komplexe Abfragen (z.B. nach Tags) effizient zu unterstützen.

## Entscheidung

Einsatz von PostgreSQL als primäre Datenbank für Metadaten, Tags und Berechtigungen.

## Konsequenzen

Die Verwendung von PostgreSQL ermöglicht robuste Relationen und ACID-Compliance für Metadaten, während S3-kompatibler Speicher die Skalierung der eigentlichen Datei-Blobs übernimmt. Dies trennt Metadaten-Logik von Storage-Logik.
