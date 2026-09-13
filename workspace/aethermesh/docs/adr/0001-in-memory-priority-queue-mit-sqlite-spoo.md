# In-Memory Priority Queue mit SQLite-Spooling für Persistenz statt reiner In-Memory-Lösung

Status: Angenommen

## Kontext

AetherMesh benötigt eine Priority-Job-Queue. Eine reine In-Memory-Lösung (z.B. asyncio.PriorityQueue) ist sehr schnell, verliert aber bei einem Crash alle anstehenden Jobs. Eine reine Datenbank-Lösung (z.B. PostgreSQL/SQLite) ist langsamer und erzeugt mehr I/O-Overhead.

## Entscheidung

Wir verwenden einen hybriden Ansatz: Eine `asyncio.PriorityQueue` für den schnellen In-Memory-Zugriff und das Routing, kombiniert mit einem asynchronen SQLite-Spooling (Write-Ahead-Log). Eingehende Jobs werden vor der Bestätigung an den Client in SQLite persistiert und bei erfolgreicher Verarbeitung gelöscht (oder in die DLQ verschiebt).

## Konsequenzen

Vorteile: Hoher Durchsatz durch In-Memory-Verarbeitung, Crash-Resilienz durch SQLite-Persistenz. Nachteile: Höhere Komplexität bei der Synchronisation zwischen Memory und Disk. Beim Startup muss die SQLite-DB ausgelesen werden, um die In-Memory-Queue zu repopulieren.
