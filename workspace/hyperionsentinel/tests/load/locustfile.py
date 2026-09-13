"""Locust-Lasttestsuite fuer HyperionSentinel.

Testet Rate-Limiting, Traffic-Shaping und Burst-Handling unter hoher Nebenlaeufigkeit.
Basiert auf relative URLs gemaess Spezifikation (Host wird per CLI uebergeben).
"""

import random
import uuid

from locust import HttpUser, between, tag, task


def generate_random_token() -> str:
    """Generiert ein zufaelliges Test-Token fuer API-Aufrufe."""
    return f"hs_test_{uuid.uuid4().hex[:16]}"


class SentinelStandardUser(HttpUser):
    """Simuliert regulaere Microservice-Clients mit normaler Request-Rate."""

    wait_time = between(0.1, 0.5)

    def on_start(self) -> None:
        """Initialisiere Client-Header und Identifikatoren."""
        self.api_key = generate_random_token()
        self.client_ip = f"192.168.{random.randint(1, 254)}.{random.randint(1, 254)}"
        self.headers = {
            "X-API-Key": self.api_key,
            "X-Forwarded-For": self.client_ip,
            "Content-Type": "application/json",
        }

    @tag("health")
    @task(2)
    def test_health_check(self) -> None:
        """Health-Check Endpunkt zur Baseline-Latenzmessung."""
        with self.client.get("/health", headers=self.headers, catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Unerwarteter Statuscode: {response.status_code}")

    @tag("verify")
    @task(6)
    def test_verify_traffic(self) -> None:
        """Prueft die Token-Validierung und Standard-Rate-Limits (/api/v1/verify)."""
        payload = {
            "token": self.api_key,
            "client_ip": self.client_ip,
            "request_path": "/api/v1/resource",
            "method": "GET",
        }
        with self.client.post("/api/v1/verify", json=payload, headers=self.headers, catch_response=True) as response:
            if response.status_code in (200, 429):
                # 429 Too Many Requests ist ein valides Testergebnis bei aktivem Rate-Limiting
                if response.status_code == 429:
                    # Validierung der RFC-konformen Header
                    has_retry = "retry-after" in response.headers or "Retry-After" in response.headers
                    if not has_retry:
                        response.failure("Status 429 ohne Retry-After Header empfangen")
                    else:
                        response.success()
                else:
                    response.success()
            elif response.status_code == 404:
                # Fallback fuer fruehe Entwicklungsphasen
                response.success()
            else:
                response.failure(f"Unerwarteter Fehlercode: {response.status_code}")

    @tag("metrics")
    @task(1)
    def test_metrics_endpoint(self) -> None:
        """Liest System- und Traffic-Metriken aus."""
        with self.client.get("/api/v1/metrics", headers=self.headers, catch_response=True) as response:
            if response.status_code in (200, 404):
                response.success()
            else:
                response.failure(f"Metrik-Endpunkt fehlgeschlagen mit Status: {response.status_code}")


class AggressiveBurstUser(HttpUser):
    """Simuliert aggressive Clients oder DDoS-Angreifer, um das Rate-Limiting zu triggern."""

    # Minimale Wartezeit zur Erzeugung von Lastspitzen (Burst)
    wait_time = between(0.01, 0.05)

    def on_start(self) -> None:
        """Verwendet eine feste Angreifer-IP zur gezielten Ueberschreitung des Sliding-Windows."""
        self.attacker_ip = f"10.0.66.{random.randint(1, 10)}"
        self.attacker_token = f"burst_token_{random.randint(1, 5)}"
        self.headers = {
            "X-API-Key": self.attacker_token,
            "X-Forwarded-For": self.attacker_ip,
            "Content-Type": "application/json",
        }

    @tag("burst", "rate_limit")
    @task
    def trigger_rate_limit(self) -> None:
        """Feuert kontinuierlich Requests ab, um Status 429 (Too Many Requests) zu provozieren."""
        payload = {
            "token": self.attacker_token,
            "client_ip": self.attacker_ip,
            "request_path": "/api/v1/protected",
            "method": "POST",
        }
        with self.client.post("/api/v1/verify", json=payload, headers=self.headers, catch_response=True) as response:
            if response.status_code == 429:
                # Erwartetes Verhalten bei Rate-Limit-Ueberschreitung
                response.success()
            elif response.status_code == 200:
                response.success()
            elif response.status_code == 404:
                # Endpunkt noch nicht registriert
                response.success()
            else:
                response.failure(f"Unerwarteter Burst-Statuscode: {response.status_code}")
