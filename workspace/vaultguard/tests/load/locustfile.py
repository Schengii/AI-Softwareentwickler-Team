from locust import HttpUser, task, between

class VaultGuardUser(HttpUser):
    wait_time = between(1, 3)
    
    def on_start(self):
        """Initialisierung für jeden User (z.B. Auth-Header setzen)"""
        self.headers = {"X-Vault-User-ID": "test-user-123"}

    @task(3)
    def list_secrets(self):
        self.client.get("/api/v1/secrets", headers=self.headers)

    @task(1)
    def create_secret(self):
        self.client.post(
            "/api/v1/secrets",
            json={
                "key": "test-key",
                "value": "secret-value",
                "environment": "production"
            },
            headers=self.headers
        )
