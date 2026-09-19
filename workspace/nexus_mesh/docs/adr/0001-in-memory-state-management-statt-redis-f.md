# In-Memory State Management statt Redis für Rate Limiting und Circuit Breaker

Status: Angenommen

## Kontext

Das API-Gateway benötigt State-Management für das Token-Bucket Rate Limiting und den Circuit Breaker. Zur Auswahl standen ein verteiltes System (Redis) oder lokales In-Memory-Management.

## Entscheidung

Wir entscheiden uns für In-Memory State Management mittels Python-Dictionaries und `asyncio.Lock` für Thread-Sicherheit bei asynchronen Zugriffen.

## Konsequenzen

Sehr hohe Performance, geringe Latenz und keine externen Abhängigkeiten (wie Redis). Das Gateway ist sofort lauffähig. Einschränkung: Bei mehreren Gateway-Instanzen (Horizontal Scaling) gelten Rate Limits pro Instanz und Circuit Breaker-States sind nicht synchronisiert. Für den aktuellen Scope eines autonomen Gateways ist dies der beste Trade-off.
