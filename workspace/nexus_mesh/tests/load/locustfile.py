from locust import HttpUser, between, task


class NexusMeshUser(HttpUser):
    """
    Lasttest für das Nexus Mesh API-Gateway.
    Testet Durchsatz und Rate-Limiting-Verhalten.
    """
    wait_time = between(0.1, 0.5)

    @task(5)
    def forward_request(self):
        # Testet das dynamische Routing/Forwarding
        # Annahme: 'test-service' ist ein konfigurierter Upstream-Service
        self.client.get("/test-service/api/data", name="/{service}/{path}")

    @task(1)
    def health_check(self):
        # Testet die System-Routen
        self.client.get("/health", name="/health")

    @task(1)
    def metrics_check(self):
        # Testet den Prometheus-Endpunkt
        self.client.get("/metrics", name="/metrics")
