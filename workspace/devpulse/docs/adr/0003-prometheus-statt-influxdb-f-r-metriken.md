# Prometheus statt InfluxDB für Metriken

Status: Angenommen

## Kontext

Die Plattform muss Zeitreihenmetriken von Microservices sammeln, abfragen und Alerts auslösen. Optionen: Prometheus (Open-Source, Pull-basiert, integrierte Alerting) vs InfluxDB (Push-basiert, proprietär).

## Entscheidung

Prometheus

## Konsequenzen

Einfaches Pull-Modell, native Integration mit Alertmanager und Grafana, aber begrenzte Langzeitaufbewahrung; erfordert zusätzliche Storage-Adapter für Langzeitarchivierung.
