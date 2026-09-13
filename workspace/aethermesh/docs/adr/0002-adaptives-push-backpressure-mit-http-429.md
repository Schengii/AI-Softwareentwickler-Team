# Adaptives Push-Backpressure mit HTTP 429 statt reinem Pull-Modell

Status: Angenommen

## Kontext

Wenn Clients mehr Jobs senden als die Worker verarbeiten können, staut sich die Queue. Ein Pull-Modell (Clients fragen, ob sie senden dürfen) erfordert Client-Anpassungen. Ein Push-Modell mit unendlicher Queue führt zu OOM (Out of Memory).

## Entscheidung

Wir implementieren einen adaptiven Backpressure-Controller, der die Queue-Größe und Worker-Auslastung überwacht. Überschreitet die Last konfigurierbare Schwellenwerte, werden eingehende POST-Requests (Push) sofort mit HTTP 429 (Too Many Requests) und einem `Retry-After`-Header abgewiesen.

## Konsequenzen

Vorteile: Schützt die Engine effektiv vor Überlastung (OOM), nutzt Standard-HTTP-Semantik, keine speziellen Client-Protokolle nötig. Nachteile: Clients müssen HTTP 429 korrekt behandeln und Retries implementieren.
