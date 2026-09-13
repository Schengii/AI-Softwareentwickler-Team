# Memory-Mapped (mmap) Append-Only WAL für Storage

Status: Angenommen

## Kontext

EventStream-Zero benötigt extrem schnelle, persistente Schreib- und Lesezugriffe für das Event-Log. Traditionelle Datenbanken oder reines File-I/O via `open()` erzeugen zu viel Overhead (Context Switches, Kopieren zwischen Kernel- und User-Space).

## Entscheidung

Implementierung eines Append-Only Write-Ahead-Logs (WAL) mit Memory-Mapped Files (`mmap`) und Sparse-Indexing.

## Konsequenzen

Hoher Durchsatz und Zero-Copy-Reads möglich. Erfordert jedoch sorgfältiges Speichermanagement (Memory Leaks, Page Cache Thrashing) und eine robuste Crash-Recovery-Strategie (Index-Rebuild bei unsauberem Shutdown).
