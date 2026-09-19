# httpx statt aiohttp für Request-Forwarding

Status: Angenommen

## Kontext

Das Gateway muss eingehende Requests asynchron und hochperformant an Downstream-Services weiterleiten. Zur Auswahl standen `aiohttp` und `httpx`.

## Entscheidung

Wir nutzen `httpx.AsyncClient` für das Request-Forwarding.

## Konsequenzen

Einfache und moderne API, synchrone und asynchrone Unterstützung, gute Testbarkeit. Es muss zwingend ein globaler `httpx.AsyncClient` mit Connection Pooling (Limits) in der App-Lifespan instanziiert werden, um Socket-Exhaustion unter Last zu vermeiden.
