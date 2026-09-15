# WebSockets statt SSE für Live-Log-Streaming

Status: Angenommen

## Kontext

Das Frontend benötigt einen Live-Stream der eingehenden Logs. Optionen sind Server-Sent Events (SSE), Long Polling oder WebSockets. WebSockets bieten geringe Latenz und bidirektionale Kommunikation.

## Entscheidung

Einsatz von WebSockets für das Live-Streaming der Logs. Ein zentraler ConnectionManager verwaltet die aktiven Verbindungen und verteilt eingehende Events per Broadcast.

## Konsequenzen

Bidirektionale Kommunikation ist möglich (z.B. für dynamische Filter-Updates vom Client zum Server ohne neue HTTP-Requests). Erfordert sauberes Connection-Management (Disconnects, Ping/Pong) im Backend.
