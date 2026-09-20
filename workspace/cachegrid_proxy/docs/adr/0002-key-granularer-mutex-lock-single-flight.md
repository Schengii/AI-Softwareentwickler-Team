# Key-granularer Mutex-Lock (Single-Flight) gegen Thundering Herd

Status: Angenommen

## Kontext

Bei parallelen Cache-Misses auf dieselbe Ressource droht Upstream-Überlastung (Thundering Herd / Cache Stampede). Alternativen: Globaler Async-Lock (Bottleneck), Probabilistisches Refresh (XFetch), Key-granulare Mutexes (Single-Flight).

## Entscheidung

Verwendung einer Registry für feingranulare `asyncio.Lock`-Instanzen pro Cache-Key mit Referenzzählung / Cleanup nach Freigabe (Single-Flight Read-Through).

## Konsequenzen

Vorteile: Maximale Parallelität bei unterschiedlichen Keys (kein globaler Flaschenhals), 100% Thundering-Herd-Schutz pro Einzelschlüssel. Nachteil: Lokale Locks müssen nach Abschluss sauber aus der Lock-Registry aufgeräumt werden, um Memory Leaks zu verhindern.
