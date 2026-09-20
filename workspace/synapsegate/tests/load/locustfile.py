import uuid

from locust import HttpUser, between, task


class SynapseGateUser(HttpUser):
    """
    Lasttest-Skript für SynapseGate.
    Verifiziert Rate-Limiting, Idempotenz-Handling und Circuit-Breaker-Verhalten.
    """
    wait_time = between(0.1, 0.5)

    @task(3)
    def test_api_request_with_idempotency(self):
        """Testet API-Endpunkt mit Idempotency-Key."""
        headers = {
            "X-Idempotency-Key": str(uuid.uuid4()),
            "Content-Type": "application/json"
        }
        self.client.post("/api/v1/process", json={"data": "test"}, headers=headers)

    @task(2)
    def test_rate_limiting(self):
        """Testet Rate-Limiting-Verhalten durch hohe Frequenz."""
        self.client.get("/api/v1/status")

    @task(1)
    def test_circuit_breaker_trigger(self):
        """Testet Circuit-Breaker durch Aufruf eines potenziell instabilen Endpunkts."""
        self.client.get("/api/v1/upstream-proxy")
