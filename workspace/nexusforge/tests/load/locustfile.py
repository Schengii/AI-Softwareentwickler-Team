# tests/load/locustfile.py
from locust import HttpUser, between, task


class NexusForgeUser(HttpUser):
    wait_time = between(0.1, 0.5)
    
    def on_start(self):
        self.headers = {"Content-Type": "application/json", "X-Tenant-ID": "test-tenant-1"}

    @task(10)
    def evaluate_flag(self):
        payload = {"context": {"user_id": "user_123", "region": "eu-central-1"}}
        self.client.post("/api/v1/flags/test-feature/evaluate", json=payload, headers=self.headers)
