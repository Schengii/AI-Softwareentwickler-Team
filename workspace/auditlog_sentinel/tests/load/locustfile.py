from locust import HttpUser, between, task


class AuditLogUser(HttpUser):
    wait_time = between(1, 3)

    @task(3)
    def get_logs(self):
        """Testet das Abrufen von Logs mit Filtern."""
        self.client.get("/api/v1/logs?service=auth&start=2023-01-01T00:00:00Z&end=2023-12-31T23:59:59Z")

    @task(1)
    def post_log(self):
        """Testet das Senden eines neuen Log-Eintrags."""
        payload = {
            "user_id": "user_123",
            "action": "login",
            "resource": "auth_service",
            "status": "success",
            "metadata": {"ip": "127.0.0.1"}
        }
        self.client.post("/api/v1/logs", json=payload)
