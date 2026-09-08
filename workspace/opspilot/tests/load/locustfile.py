from locust import HttpUser, between, task


class IncidentIngestionUser(HttpUser):
    """
    Lasttest für Incident Ingestion und Workflow Triggers.
    Ziel: High-Throughput Ingestion und Trigger-Performance.
    """
    wait_time = between(0.1, 0.5)

    @task(3)
    def ingest_incident(self):
        """Testet die Ingestion von Incidents."""
        payload = {
            "title": "High CPU Usage",
            "severity": "critical",
            "source": "monitoring-agent-01",
            "metadata": {"node": "prod-worker-01"}
        }
        self.client.post("/api/v1/incidents", json=payload)

    @task(1)
    def trigger_workflow(self):
        """Testet das Triggern eines Workflows."""
        self.client.post("/api/v1/workflows/trigger", json={"incident_id": "test-id-123"})
