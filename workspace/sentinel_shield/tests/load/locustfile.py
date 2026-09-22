from locust import HttpUser, task, between
import random

class SentinelShieldUser(HttpUser):
    wait_time = between(0.1, 0.5)

    @task(3)
    def dispatch_request(self):
        # Simuliert einen Request an das Gateway
        # Erwartet, dass der Host über --host beim Start übergeben wird
        headers = {"Authorization": "Bearer test-token-123"}
        self.client.post("/api/v1/dispatch", json={"target": "service-a", "payload": "data"}, headers=headers)

    @task(1)
    def check_health(self):
        self.client.get("/api/v1/health")

    @task(1)
    def get_metrics(self):
        self.client.get("/api/v1/metrics")
