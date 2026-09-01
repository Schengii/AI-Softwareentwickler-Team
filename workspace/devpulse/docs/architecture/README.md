# Architektur‑Übersicht

Dieses Verzeichnis enthält Artefakte, die die Gesamtarchitektur von **DevPulse** dokumentieren.

## Diagramm

- **`diagram.c4.md`** – Vollständiges C4‑Diagramm (Mermaid) mit allen System‑ und Datenbank‑Komponenten sowie deren Beziehungen.
- Das Diagramm spiegelt die Entscheidungen aus den ADRs wider:
  - **ADR 0001** – Kubernetes als Orchestrierung
  - **ADR 0002** – Go für Microservices
  - **ADR 0003** – Prometheus für Metriken
  - **ADR 0004** – gRPC für interne Service‑APIs

## Verweise

- `../adr/0001-kubernetes-statt-docker-swarm-f-r-orches.md`
- `../adr/0002-go-statt-java-f-r-microservices.md`
- `../adr/0003-prometheus-statt-influxdb-f-r-metriken.md`
- `../adr/0004-grpc-statt-rest-f-r-interne-service-apis.md`

## Weiteres Vorgehen

- Ergänzen eines **Deployment‑Diagramms** (C4‑Container → Deployment) sobald Kubernetes‑Manifeste finalisiert sind.
- Pflege der Diagramme bei Einführung neuer Services (z. B. Auth‑Service, Billing‑Service).

