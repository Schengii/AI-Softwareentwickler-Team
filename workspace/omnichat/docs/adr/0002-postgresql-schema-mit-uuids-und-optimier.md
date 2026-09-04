# PostgreSQL-Schema mit UUIDs und optimierten Indizes für Messaging

Status: Angenommen

## Kontext

Für die Chat-Plattform OmniChat ist eine performante Abfrage der Nachrichten nach Kanal und Zeitstempel kritisch. Wir benötigen eine robuste, normalisierte Struktur für Nutzer, Kanäle und Nachrichten. PostgreSQL wurde gewählt, da es exzellente Unterstützung für JSONB (für spätere Erweiterungen wie Metadaten) und komplexe Indizes bietet.

## Entscheidung

Verwendung von UUIDs als Primärschlüssel und ein zusammengesetzter Index auf (channel_id, created_at DESC) für die Nachrichten-Tabelle.

## Konsequenzen

- Vorteil: Schnelle Abfragen der Nachrichtenverläufe pro Kanal durch den zusammengesetzten Index.
- Vorteil: Einfache Skalierbarkeit durch UUIDs statt sequentieller IDs.
- Nachteil: UUIDs sind größer als BIGINT, was bei extrem hohen Datenmengen den Speicherbedarf leicht erhöht.
- Einschränkung: Fremdschlüssel-Constraints erzwingen referenzielle Integrität, was bei Massen-Inserts beachtet werden muss.
