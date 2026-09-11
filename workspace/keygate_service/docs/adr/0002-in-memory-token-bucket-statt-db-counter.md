# In-Memory Token-Bucket statt DB-Counter für Rate-Limiting

Status: Angenommen

## Kontext

Rate-Limiting pro API-Key benötigt einen Zähler-Mechanismus mit Token-Bucket-Semantik (Quota + Refill-Rate). Alternativen: (a) Zähler/Timestamps in SQLite je Request lesen/schreiben, (b) In-Memory-Datenstruktur (dict, thread-safe) im Prozess. Redis wurde als Alternative verworfen, da der Service laut Anforderung als Single-Node-Microservice mit SQLite ausgeliefert wird und keine externe Infrastruktur voraussetzen soll.

## Entscheidung

Token-Bucket-Zustand (aktuelle Tokens, letzter Refill-Zeitpunkt) wird In-Memory pro Prozess in app/services/rate_limiter.py (TokenBucketLimiter, dict[key_id -> Bucket], threading.Lock) gehalten. Quota und Refill-Rate stammen aus der DB (ApiKey.rate_limit_per_minute), der Laufzeitzustand des Buckets lebt nur im Speicher. Bei Prozess-Neustart werden alle Buckets auf volle Kapazität zurückgesetzt (akzeptiert, siehe Consequences).

## Konsequenzen

Vorteil: keine zusätzliche DB-Last pro Request (kein Write auf SQLite bei jedem /verify-Call), niedrige Latenz, einfache Graceful-Degradation (bei Lock-Contention wird konservativ 429 zurückgegeben statt zu blockieren). Nachteil: NICHT horizontal skalierbar über mehrere Prozesse/Instanzen hinweg (jede Instanz hat eigenen Bucket-Zustand) - für Mehrinstanz-Deployment wäre Redis nötig (zukünftiges ADR bei Bedarf). Zustand geht bei Neustart verloren (kein Sicherheitsrisiko, nur Quota-Reset). Muss in README als bekannte Grenze dokumentiert werden.
