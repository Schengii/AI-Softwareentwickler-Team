# IncidentPilot – Architekturübersicht

## 1. Architektur‑Stil
Wir setzen **Microservice‑Architektur** ein. Jeder Service ist eigenständig deploy‑bar, skaliert unabhängig und kommuniziert über HTTP/REST. Das ermöglicht klare Trennung von Frontend, Backend‑API, Auth‑Service und optionalen Hintergrund‑Jobs (z. B. Scheduler).

## 2. Systemkomponenten
| Service | Technologie | Verantwortung |
|--------|--------------|----------------|
| **Frontend** | React (Vite) | UI, Interaktion, Aufruf der Public‑API |
| **API‑Gateway / Edge** | Nginx (optional) | TLS‑Termination, Routing |
| **Auth‑Service** | FastAPI | OAuth2‑Password‑Bearer, JWT‑Issuing, Refresh‑Token, Rollen‑Management |
| **Check‑Service** | FastAPI | CRUD für Checks, Ausführen von HTTP‑Probes, Persistieren von `CheckResult` |
| **Metrics‑Service** | FastAPI | Exponiert Prometheus‑Metriken (`/metrics`) |
| **Datenbank** | PostgreSQL | Persistente Speicherung von `User`, `Check`, `CheckResult` |
| **Cache** | Redis (optional) | Zwischenspeichern von Check‑Status, Rate‑Limiting |

## 3. API‑Contracts (OpenAPI 3.0)
Siehe `architecture/openapi.yaml` – definiert Endpunkte für Checks, Status und Metriken.

## 4. Datenmodell (SQLAlchemy)
Siehe `architecture/models.py` – enthält Entity‑Definitionen für `User`, `Check` und `CheckResult`.

## 5. Authentifizierungs‑Strategie
* **OAuth2 Password Bearer** mit **JWT** für Access‑Token (15 min).
* **Refresh‑Token** (7 Tage) zur Token‑Erneuerung.
* Rollen‑basierte Zugriffskontrolle (`admin`, `user`).

## 6. Weiteres
* **Event‑Driven**: Check‑Ausführung kann über Celery (RabbitMQ) ausgelagert werden (nicht Teil des Minimal‑MVP).
* **CI/CD**: Docker‑Compose für lokale Entwicklung, Helm‑Charts für Produktion.
