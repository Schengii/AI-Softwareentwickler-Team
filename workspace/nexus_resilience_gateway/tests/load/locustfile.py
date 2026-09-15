import hashlib
import hmac
import json
import time

from locust import HttpUser, between, task


class NexusGatewayUser(HttpUser):
    """
    Lasttest für das Nexus Resilience Gateway.
    Simuliert API-Anfragen mit HMAC-Signaturprüfung.
    """
    wait_time = between(0.1, 0.5)  # Aggressives Intervall für hohe Concurrency

    def on_start(self):
        self.tenant_id = "test-tenant"
        self.secret = b"super-secret-key"

    def _generate_signature(self, payload: str, timestamp: str) -> str:
        message = f"{timestamp}{payload}".encode()
        return hmac.new(self.secret, message, hashlib.sha256).hexdigest()

    @task(10)
    def proxy_request(self):
        """Simuliert eine validierte Proxy-Anfrage."""
        timestamp = str(int(time.time()))
        payload = json.dumps({"data": "test-payload"})
        signature = self._generate_signature(payload, timestamp)
        
        headers = {
            "X-Tenant-ID": self.tenant_id,
            "X-Signature": signature,
            "X-Timestamp": timestamp,
            "Content-Type": "application/json"
        }
        
        self.client.post(
            "/proxy/target-service",
            data=payload,
            headers=headers,
            catch_response=True
        )

    @task(1)
    def get_metrics(self):
        """Simuliert den Abruf von Gateway-Metriken."""
        self.client.get("/metrics", catch_response=True)
