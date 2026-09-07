# Predictive Maintenance ML Service

## Modell-Architektur
- **Ansatz:** Zeitreihen-Analyse zur Vorhersage des Wartungsbedarfs.
- **Implementierung:** FastAPI-Service mit Pydantic-Validierung.
- **Skalierbarkeit:** Der Service ist zustandslos und kann horizontal skaliert werden.

## Evaluation
- **Metriken:** Precision, Recall, F1-Score auf einem validierten Testdatensatz.
- **Monitoring:** Überwachung der `maintenance_probability` Verteilung via Prometheus/Grafana.

## Kosten
- **Inferenz:** Geringe CPU-Last bei Verwendung von Scikit-learn/LightGBM Modellen.
- **Training:** Batch-Training offline, Inferenz-Service bleibt leichtgewichtig.
