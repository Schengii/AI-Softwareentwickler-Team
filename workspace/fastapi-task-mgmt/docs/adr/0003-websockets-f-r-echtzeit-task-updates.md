# WebSockets für Echtzeit-Task-Updates

Status: Angenommen

## Kontext

Anforderung für Echtzeit-Updates bei Task-Statusänderungen. Option: Polling vs. WebSockets. Entscheidung: WebSockets für geringere Latenz.

## Entscheidung

Einsatz von WebSockets für Task-Updates.

## Konsequenzen

Vorteil: Echtzeit-Synchronisation ohne Polling. Nachteil: Erfordert WebSocket-Handling im Backend und Client-seitige Verbindungsüberwachung.
