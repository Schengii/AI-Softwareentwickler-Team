# ADR 0006: Event-Driven Anomaly Processing

## Status
Angenommen

## Kontext
Um die Skalierbarkeit der Anomalie-Erkennung zu gewährleisten, muss die Ingestion von Metriken von der rechenintensiven Analyse entkoppelt werden.

## Entscheidung
Wir führen ein asynchrones Pub/Sub-Modell ein.
1. **Ingestion:** API-Endpunkte schreiben eingehende Metriken in eine `asyncio.Queue` (in-memory für MVP, später Redis).
2. **Worker:** Ein Hintergrund-Task (Worker) konsumiert die Queue und führt die Analyse durch.
3. **Event-Schema:** Anomalien werden als Events in eine dedizierte Anomalie-Tabelle geschrieben.

## Konsequenzen
- **Vorteil:** API-Antwortzeiten bleiben stabil, unabhängig von der Analyse-Last.
- **Nachteil:** Erhöhte Komplexität durch Hintergrund-Tasks.
