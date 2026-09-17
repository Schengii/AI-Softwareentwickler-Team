# In-Memory-Ringpuffer für Backpressure

Status: Angenommen

## Kontext

Die Ingestion-API muss Lastspitzen abfangen und Backpressure (HTTP 429) signalisieren, wenn das System überlastet ist.

## Entscheidung

Implementierung eines In-Memory-Ringpuffers (z.B. collections.deque mit maxlen) für eingehende Telemetriedaten. Wenn der Puffer voll ist, wird synchron 429 Too Many Requests zurückgegeben. Ein Hintergrund-Task verarbeitet den Puffer asynchron.

## Konsequenzen

Bei einem Absturz gehen die Daten im Puffer verloren (In-Memory). Schützt das System effektiv vor Überlastung. Die Puffergröße muss sorgfältig konfiguriert werden.
