# Sicheres Pydantic-Settings Management ohne unsichere Defaults

Status: Angenommen

## Kontext

Die bisherige Settings-Klasse hatte unsichere Default-Werte für SECRET_KEY und API_KEY, was zu Sicherheitsrisiken führte. Zudem gab es Unklarheiten bei der Pydantic-Konfiguration.

## Entscheidung

Entfernung der unsicheren Default-Strings. Nutzung von Pydantic Field(..., ...) um Pflichtfelder zu erzwingen. Validatoren bleiben zur Sicherstellung der Mindestlänge.

## Konsequenzen

Erzwingt explizite Konfiguration über Umgebungsvariablen in Produktion, verhindert unsichere Defaults. Erfordert .env Datei oder gesetzte Umgebungsvariablen für Tests.
