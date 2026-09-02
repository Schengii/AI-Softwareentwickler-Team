# Sicherheits- und Resilienz-Integration im API-Gateway

Status: Angenommen

## Kontext

Das API-Gateway benötigt Schutz gegen gängige Web-Angriffe und muss bei Upstream-Ausfällen stabil bleiben. Bisher fehlten Sicherheitsheader, Input-Validierung und eine robuste Fehlerbehandlung.

## Entscheidung

Implementierung von Security-Middleware, Pfad-Sanitization und Integration der `resilience_guard`-Logik direkt in die Proxy-Route. Nutzung von `httpx.Timeout` für alle Upstream-Aufrufe.

## Konsequenzen

Erhöhte Sicherheit durch strikte Header-Richtlinien und Input-Validierung. Proxy-Stabilität durch integrierte Resilienz-Muster (Retry/Circuit Breaker) und explizite Timeouts. Mögliche Performance-Einbußen durch Middleware-Overhead sind vernachlässigbar.
