# Native WebSockets statt Socket.IO für Live-Updates

Status: Angenommen

## Kontext

Das Web-Dashboard benötigt Live-Updates über den Status der Workflows. Optionen: HTTP Polling, Native WebSockets, Socket.IO.

## Entscheidung

Wir nutzen Native WebSockets (`websockets` / `uvicorn[standard]`), um bekannte Handshake-Fehler (wie 'Connection header is missing') durch inkompatible Polling-Fallbacks von Socket.IO zu vermeiden.

## Konsequenzen

Frontend muss Reconnect-Logik selbst implementieren. Keine Abhängigkeit zu Socket.IO-Libraries, Vermeidung von Handshake-Problemen.
