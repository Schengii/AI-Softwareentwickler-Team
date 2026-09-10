# SQLAlchemy 2.0 Async relationales Schema für Observability, Alerts und Incidents

Status: Angenommen

## Kontext

LogiPulse benötigt ein performantes, typ-sicheres Schema für Realtime Observability (Metriken, Traces, Anomalien), Alerts und Incident Management mit AI Copilot Empfehlungen.

## Entscheidung

Verwendung von SQLAlchemy 2.0 Async ORM mit explizit definierten Modellen für Metriken, Traces, Anomalien, Alert-Regeln, Triggered Alerts, Incidents, Incident-Timeline und Copilot-Empfehlungen in einem zentralen Base-Registry-Pattern (app/db/base.py).

## Konsequenzen

1. SQLAlchemy 2.0 Async mit AsyncSession ermöglicht hocheffizienten async/await Betrieb in FastAPI.
2. Für die lokale Entwicklung und automatisierte Tests nutzen wir aiosqlite mit StaticPool, während für die Produktion PostgreSQL mit asyncpg vorgesehen ist.
3. Zeitreihen- und Trace-Tabellen sind mit Indizes auf (service_name, timestamp) bzw. trace_id optimiert, um schnellen Zugriff für AI Copilot und Dashboard-APIs zu garantieren.
