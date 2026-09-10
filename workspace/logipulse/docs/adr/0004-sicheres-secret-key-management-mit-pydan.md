# Sicheres Secret-Key-Management mit Pydantic-Validierung

Status: Angenommen

## Kontext

Das Projekt hatte ein unsicheres Secret-Key-Management, bei dem der Key aus der Umgebung ohne Validierung geladen wurde. Dies ist ein Sicherheitsrisiko für die JWT-Authentifizierung.

## Entscheidung

Einführung eines Pydantic-Validators in der Settings-Klasse, der die Mindestlänge des SECRET_KEY auf 32 Zeichen prüft.

## Konsequenzen

Erhöhte Sicherheit durch erzwungene Mindestlänge des Secret Keys. Verhindert Start der Anwendung bei unsicherer Konfiguration.
