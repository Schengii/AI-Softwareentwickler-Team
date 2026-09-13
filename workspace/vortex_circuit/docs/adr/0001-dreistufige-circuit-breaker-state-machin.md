# Dreistufige Circuit-Breaker State-Machine

Status: Angenommen

## Kontext

Externe Microservices können ausfallen oder überlastet sein. Ein unkontrolliertes Weiterleiten von Anfragen führt zu Ressourcenerschöpfung (Cascading Failures). Es muss entschieden werden, wie der Zustand des externen Dienstes überwacht und Anfragen gesteuert werden. Optionen: 1) Einfacher Retry, 2) Circuit Breaker mit 3 Zuständen (Closed, Open, Half-Open).

## Entscheidung

Implementierung einer dreistufigen Circuit-Breaker State-Machine (Closed, Open, Half-Open). Im CLOSED-Zustand werden Anfragen normal weitergeleitet. Bei Überschreiten von Fehlerraten oder aufeinanderfolgenden Fehlern wechselt der Zustand zu OPEN (Fast-Fail mit HTTP 503). Nach einer Cooldown-Phase wechselt der Zustand zu HALF-OPEN, um mit einer begrenzten Anzahl von Test-Requests die Genesung des Dienstes zu prüfen.

## Konsequenzen

- Erfordert persistente Speicherung des Zustands (z.B. in-memory mit Thread-Safety oder Redis für verteilte Systeme, hier zunächst in-memory/DB für Einfachheit).
- Aufrufer müssen mit HTTP 503 (Service Unavailable) umgehen können.
- Die Metriken-Erfassung wird komplexer, da Transitionen getrackt werden müssen.
