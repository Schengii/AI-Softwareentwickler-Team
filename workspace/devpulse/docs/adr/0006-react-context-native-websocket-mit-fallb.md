# React Context & Native WebSocket mit Fallback für DevPulse Frontend

Status: Angenommen

## Kontext

Für das DevPulse Frontend wird eine performante, echtzeitfähige State-Management- und Kommunikationslösung benötigt, die sowohl REST-APIs als auch WebSockets unterstützt und auch ohne laufendes Backend voll funktionsfähig bleibt.

## Entscheidung

Verwendung von React Context + custom Hooks in Verbindung mit einem typisierten Axios API-Client (mit Exponential Backoff) und nativer WebSocket-Verbindung mit automatischem Fallback auf Mock-Daten/Events.

## Konsequenzen

1. Einfaches State-Management ohne externe schwere Libraries wie Redux.
2. Nahtlose Umschaltung zwischen realem Backend (REST/WS) und Simulations-/Mock-Modus bei Verbindungsverlust.
3. Klare Reconnect-Strategie bei WebSocket-Trennungsereignissen.
