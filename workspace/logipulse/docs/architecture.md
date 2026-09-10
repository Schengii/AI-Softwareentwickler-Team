# LogiPulse Architektur-Dokumentation

## 1. Systemübersicht
LogiPulse ist eine AI-gestützte Plattform für Realtime API Observability und Incident Management. Das System zielt darauf ab, Anomalien in API-Traffic zu erkennen und automatisierte Empfehlungen zur Fehlerbehebung zu geben.

## 2. Datenmodell
Das Datenmodell basiert auf einer relationalen Struktur, optimiert für asynchrone Datenbankzugriffe.
*   **Referenz:** Siehe [ADR 0001: SQLAlchemy 2.0 Async Relationales Schema](adr/0001-sqlalchemy-2-0-async-relationales-schema.md).

## 3. API-Referenz
Die Kommunikation zwischen Frontend und Backend erfolgt über folgende REST-Endpunkte:

| Endpunkt | Beschreibung |
| :--- | :--- |
| `/api/v1/metrics/summary` | Abruf der aggregierten Metriken des API-Traffics. |
| `/api/v1/anomalies` | Auflistung erkannter Anomalien im System. |
| `/api/v1/traces` | Abruf detaillierter Traces für Incident-Analysen. |

## 4. Frontend-Integration
Das Frontend ist als Single Page Application (SPA) konzipiert, um eine reaktive Nutzererfahrung zu gewährleisten.
*   **Technologie:** React mit Vite und TypeScript.
*   **Design-System:** Dark Mode (Background `#0B0F19`, Primary `#6366F1`).
*   **Referenz:** Siehe [ADR 0002: React SPA mit TypeScript/Vite](adr/0002-react-spa-mit-typescript-vite-api-fallba.md).
