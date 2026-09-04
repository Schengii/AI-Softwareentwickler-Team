# UUID v4 für Primärschlüssel

Status: Angenommen

## Kontext

Für die Primärschlüssel in CloudVault wurde zwischen UUIDs und sequentiellen Integern gewählt. Aufgrund der Microservices-Architektur sind UUIDs für verteilte Systeme besser geeignet.

## Entscheidung

Verwendung von UUID v4 als Primärschlüssel für alle Tabellen.

## Konsequenzen

Vorteile: Eindeutige Identifikation der Entitäten, gute Skalierbarkeit, einfache Integration mit modernen Backend-Frameworks. Nachteile: Etwas höherer Speicherbedarf als bei Integer-IDs.
