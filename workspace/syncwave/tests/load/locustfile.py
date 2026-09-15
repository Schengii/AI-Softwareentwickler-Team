import random

from locust import HttpUser, between, task


class LogMonitoringUser(HttpUser):
    wait_time = between(0.1, 0.5)

    @task(4)
    def post_log(self):
        """Simuliert das Senden von Log-Events."""
        payload = {
            "level": random.choice(["INFO", "WARN", "ERROR", "DEBUG"]),
            "service_name": random.choice(["auth-service", "payment-service", "gateway"]),
            "message": "Test log message",
            "payload": {"key": "value"}
        }
        self.client.post("/api/v1/logs", json=payload)

    @task(1)
    def get_logs(self):
        """Simuliert das Abrufen der Log-Historie."""
        self.client.get("/api/v1/logs?limit=50")

    @task(1)
    def get_stats(self):
        """Simuliert das Abrufen der Statistiken."""
        self.client.get("/api/v1/stats")
