# In-Memory Message Broker mit asyncio.Queue für MVP

Status: Angenommen

## Kontext

Für das MVP benötigen wir eine asynchrone Entkopplung von Ingestion und Verarbeitung. Ein externer Broker wie RabbitMQ wäre für den aktuellen Stand Overkill. Wir benötigen jedoch eine Struktur, die später leicht auf Redis umgestellt werden kann.

## Entscheidung

Verwendung von `asyncio.Queue` als in-memory Message Broker für das MVP, um die Entkopplung gemäß ADR-0006 zu realisieren.

## Konsequenzen

- Einfachheit: Keine zusätzliche Infrastruktur für den MVP erforderlich.\n- Skalierbarkeit: Späterer Umstieg auf Redis Streams durch Austausch der Queue-Implementierung möglich.\n- Performance: Nicht-blockierende Ingestion durch asyncio.Queue.\n- Wartbarkeit: Standard-Python-Bibliotheken, keine externen Broker-Abhängigkeiten im ersten Schritt.
