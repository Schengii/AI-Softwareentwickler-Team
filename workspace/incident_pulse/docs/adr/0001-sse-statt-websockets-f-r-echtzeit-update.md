# SSE statt WebSockets für Echtzeit-Updates

Status: Angenommen

## Kontext

Echtzeit-Updates für das Dashboard werden benötigt. Zur Auswahl standen WebSockets (bidirektional) und Server-Sent Events (SSE, unidirektional).

## Entscheidung

Wir entscheiden uns für Server-Sent Events (SSE) mit 'text/event-stream'.

## Konsequenzen

Einfachere Implementierung auf Client-Seite (EventSource), funktioniert gut über Standard HTTP/1.1 und HTTP/2, native Browser-Unterstützung. Unidirektional (nur Server zu Client), was für Dashboard-Updates ausreichend ist. Keine bidirektionale Kommunikation möglich, was aber hier nicht gefordert ist.
