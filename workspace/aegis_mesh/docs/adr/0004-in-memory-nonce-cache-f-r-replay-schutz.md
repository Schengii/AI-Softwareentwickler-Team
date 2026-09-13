# In-Memory Nonce Cache für Replay-Schutz

Status: Angenommen

## Kontext

Für den Replay-Schutz müssen Nonces für die Dauer des Timestamp-Drifts (300 Sekunden) gespeichert werden, um Mehrfachverwendung zu erkennen. Optionen: Redis, Datenbank oder In-Memory.

## Entscheidung

Wir verwenden ein In-Memory Dictionary (`_nonce_cache`) mit einer Bereinigungsfunktion (`_cleanup_nonce_cache`), die abgelaufene Nonces entfernt.

## Konsequenzen

- Sehr schnell und synchron nutzbar.
- Bei Neustart des Gateways ist der Cache leer (akzeptabel, da Drift-Fenster nur 5 Min beträgt).
- Bei Multi-Worker Deployments (z.B. Gunicorn mit mehreren Uvicorn-Workern) teilen sich die Worker den Cache nicht. Für ein echtes verteiltes Setup müsste Redis verwendet werden. Für die aktuelle Gateway-Instanz ausreichend.
