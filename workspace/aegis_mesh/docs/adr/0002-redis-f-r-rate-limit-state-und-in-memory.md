# Redis für Rate-Limit State und In-Memory Fallback

Status: Angenommen

## Kontext

Speicherung der Rate-Limit-Zähler. Die Speicherung muss extrem schnell sein (< 5ms Latenz) und idealerweise über mehrere Gateway-Instanzen hinweg synchronisiert werden können. Optionen: Relationale DB, In-Memory (lokal), Redis.

## Entscheidung

Wir nutzen Redis als primären Datastore für Rate-Limits, um verteilte Instanzen zu unterstützen. Als Fallback und für Tests implementieren wir einen In-Memory-Storage.

## Konsequenzen

Einführung einer Redis-Abhängigkeit für den Produktionseinsatz. Erfordert asynchrone Redis-Clients (redis.asyncio). Für lokale Entwicklung und Tests muss ein In-Memory-Fallback (z.B. Python dict) implementiert werden, um die Einstiegshürde niedrig zu halten.
