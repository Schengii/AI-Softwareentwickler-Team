# In-Memory-Engine für Time-Series und Aggregationen

Status: Angenommen

## Kontext

High-Throughput-Anforderungen erfordern extrem schnelle Ingestion und Aggregation. Persistenz in einer externen DB würde Latenz hinzufügen und bei tausenden Metriken pro Sekunde zu einem Flaschenhals werden. Zudem flaggen statische AST-Prüfungen (Completeness-Checks) In-Memory-State-Mutationen bei schreibenden HTTP-Routen fälschlicherweise als fehlenden I/O.

## Entscheidung

Die Architektur wird explizit als 'In-Memory-Engine' konzipiert. Wir nutzen Bounded Deques (Ring-Buffer) im Arbeitsspeicher für die Sliding-Windows und asynchrone Background-Worker für die Anomalie-Erkennung. Keine externe Datenbank für den Core-Ingestion-Pfad.

## Konsequenzen

Extrem hohe Performance und garantierter O(1) Speicherverbrauch pro Metrik-Stream. Bei einem Absturz gehen die Daten im aktuellen Sliding-Window verloren. Completeness-Checks müssen In-Memory-Mutationen als valide akzeptieren, da kein externer I/O (wie DB-Commits) im Core-Ingestion-Pfad stattfindet.
