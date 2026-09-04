# Resilienz-Bibliotheken für Python

Status: Angenommen

## Kontext

Wie werden Resilienz-Patterns (Retry, Circuit Breaker) implementiert? Alternativen: Manuelle Implementierung mit `tenacity` oder `resilience4j` (Java-fokussiert).

## Entscheidung

Nutzung von `tenacity` für Retries und `aiocircuitbreaker` für Circuit Breaking.

## Konsequenzen

Erhöhte Komplexität durch zusätzliche Abhängigkeit. Bietet jedoch standardisierte Resilienz-Patterns (Retry, Circuit Breaker), die manuell schwer fehlerfrei zu implementieren sind.
