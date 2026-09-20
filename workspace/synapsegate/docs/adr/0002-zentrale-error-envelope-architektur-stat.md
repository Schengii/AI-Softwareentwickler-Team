# Zentrale Error-Envelope-Architektur statt dezentralem Error-Handling

Status: Angenommen

## Kontext

Die Anforderung verlangt eine 'Saubere Error-Envelope-Architektur' und 'Zero-Trust Input Validation', um zu verhindern, dass interne Fehlerdetails (500er Tracebacks) nach außen dringen.

## Entscheidung

Implementierung eines globalen Exception-Handlers in FastAPI, der alle Exceptions fängt und in ein standardisiertes JSON-Envelope-Format (`{'error': {'code': '...', 'message': '...'}}`) übersetzt.

## Konsequenzen

Konsistente, sichere API-Antworten. Verhindert das Leaken von Stacktraces oder internen Systemdetails. Erfordert, dass alle Domänen-Fehler von einer Basis-Exception (z.B. `AppError`) erben, um sie gezielt mappen zu können. Unbekannte Fehler werden als generischer 500er mit Maskierung geloggt.
