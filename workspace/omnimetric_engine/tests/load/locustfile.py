import random

from locust import HttpUser, between, task


class IngestionUser(HttpUser):
    """
    Lasttest für den Ingestion-Endpunkt der OmniMetric-Engine.
    Simuliert eine hohe Anzahl an Metrik-Ingestion-Requests.
    """
    wait_time = between(0.01, 0.1)  # Sehr kurze Wartezeit für hohen Durchsatz

    @task(10)
    def ingest_metric(self):
        metric_name = random.choice(["cpu_usage", "memory_usage", "latency_ms", "error_rate"])
        payload = {
            "name": metric_name,
            "value": random.uniform(0, 100),
            "timestamp": None  # Server setzt Zeitstempel
        }
        self.client.post("/api/ingest", json=payload)

    @task(1)
    def get_metrics_summary(self):
        """Simuliert gelegentliche Abfragen der aggregierten Daten."""
        self.client.get("/api/metrics/summary")
