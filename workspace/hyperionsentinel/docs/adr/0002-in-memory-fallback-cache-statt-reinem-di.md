# In-Memory Fallback-Cache statt reinem Distributed State bei DB-Ausfall

Status: Angenommen

## Kontext

Die Rate-Limiting-Engine benötigt einen hochverfügbaren Speicher. Fällt der primäre verteilte Speicher (Redis) aus, darf die Security-Engine nicht blockieren oder den gesamten Traffic durchlassen (Fail-Open) bzw. blockieren (Fail-Closed).

## Entscheidung

Implementierung eines Circuit-Breakers mit Graceful Degradation: Bei Ausfall des primären Speichers wird transparent auf einen speichereffizienten In-Memory-Fallback (LRU/TTL-Cache) umgeschaltet.

## Konsequenzen

Erhöht die Resilienz des Systems drastisch. Bei Ausfall der primären DB (z.B. Redis) läuft das Rate-Limiting pro Instanz weiter. Nachteil: Im Fallback-Modus ist der State nicht mehr über mehrere Instanzen synchronisiert, was zu leicht ungenauem Rate-Limiting (lokal pro Instanz) führt, aber die Verfügbarkeit sichert.
