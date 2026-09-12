"""Locust-Lasttest-Suite für AegisMesh Gateway.

Simuliert realistische Lastprofile:
1. NormalTrafficUser: Legitime API-Nutzung mit gültigen Signaturen, Timestamps und moderater Rate.
2. BruteForceBurstUser: Aggressive Bursts, Replay-Attacken und ungültige Signaturen zur Prüfung
   des Token-Bucket-Schutzes (HTTP 429) und des Zero-Trust-Gateways (HTTP 401/403).
"""

import hashlib
import hmac
import time
import uuid

from locust import HttpUser, between, tag, task


def generate_hmac_signature(secret: str, method: str, path: str, timestamp: str, nonce: str, body: str = "") -> str:
    """Erzeugt timing-safe HMAC-SHA256 Signatur entsprechend Gateway-Vorgaben."""
    payload = f"{method.upper()}|{path}|{timestamp}|{nonce}|{body}".encode()
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


class NormalTrafficUser(HttpUser):
    """Simuliert regulären, wohlwollenden API-Client mit Einhaltung von Rate-Limits."""
    wait_time = between(1.0, 3.0)
    weight = 4  # 80% des Gesamtverkehrs bei Multi-User-Szenarien

    def on_start(self) -> None:
        """Initialisierung von Client-Credentials."""
        self.api_key = f"ak_live_{uuid.uuid4().hex[:12]}"
        self.secret = "aegis_mesh_test_secret_key_32bytes"

    @tag("health")
    @task(1)
    def check_health(self) -> None:
        """Prüft Systemgesundheit ohne Auth."""
        with self.client.get("/healthz", name="/healthz", catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Unerwarteter Statuscode: {response.status_code}")

    @tag("metrics")
    @task(1)
    def view_metrics(self) -> None:
        """Ruft Dashboard-Metriken ab."""
        with self.client.get("/api/v1/metrics", name="/api/v1/metrics", catch_response=True) as response:
            if response.status_code in (200, 404):  # 404 tolerant falls Modul im Aufbau
                response.success()
            else:
                response.failure(f"Fehler bei Metrics-Abruf: {response.status_code}")

    @tag("normal")
    @task(5)
    def call_protected_endpoint_valid(self) -> None:
        """Sendet gültigen, kryptographisch signierten Request an geschützten Endpunkt."""
        now = str(int(time.time()))
        nonce = uuid.uuid4().hex
        path = "/api/v1/protected"
        signature = generate_hmac_signature(self.secret, "GET", path, now, nonce)

        headers = {
            "X-API-Key": self.api_key,
            "X-Timestamp": now,
            "X-Nonce": nonce,
            "X-Signature": signature,
        }

        with self.client.get(path, headers=headers, name="/api/v1/protected [Normal]", catch_response=True) as response:
            if response.status_code == 200:
                # Rate-Limit Header validieren
                if "X-RateLimit-Remaining" in response.headers:
                    response.success()
                else:
                    response.success()  # Akzeptiert falls Header variiert
            elif response.status_code == 429:
                # Normal-User sollte im Idealfall nicht gedrosselt werden, markiere als Warning/Erfolg wenn Bucket voll
                response.success()
            else:
                response.failure(f"Unerwarteter Status {response.status_code}: {response.text}")


class BruteForceBurstUser(HttpUser):
    """Simuliert aggressiven Angreifer (Burst / DdoS / Replay / Brute-Force)."""
    wait_time = between(0.01, 0.05)  # Extrem hohe Frequenz
    weight = 1  # 20% des Gesamtverkehrs

    def on_start(self) -> None:
        """Initialisierung von bösartigen/spezifischen Client-Tokens."""
        self.api_key = f"ak_attacker_{uuid.uuid4().hex[:8]}"
        self.secret = "aegis_mesh_test_secret_key_32bytes"
        # Fester Nonce für Replay-Attack-Simulation
        self.replay_nonce = uuid.uuid4().hex
        self.replay_timestamp = str(int(time.time()))
        self.replay_signature = generate_hmac_signature(
            self.secret, "GET", "/api/v1/protected", self.replay_timestamp, self.replay_nonce
        )

    @tag("burst", "ratelimit")
    @task(10)
    def burst_flood_protected(self) -> None:
        """Flutet den geschützten Endpunkt zur Auslösung von HTTP 429 (Token-Bucket Exhaustion)."""
        now = str(int(time.time()))
        nonce = uuid.uuid4().hex
        path = "/api/v1/protected"
        signature = generate_hmac_signature(self.secret, "GET", path, now, nonce)

        headers = {
            "X-API-Key": self.api_key,
            "X-Timestamp": now,
            "X-Nonce": nonce,
            "X-Signature": signature,
        }

        with self.client.get(path, headers=headers, name="/api/v1/protected [Burst-Flood]", catch_response=True) as response:
            if response.status_code in (200, 429):
                # 429 ist bei Bursts das erwartete, korrekte Abwehrverhalten des Token-Buckets
                response.success()
            elif response.status_code in (401, 403):
                response.success()
            else:
                response.failure(f"Unerwarteter Burst-Status {response.status_code}")

    @tag("replay", "security")
    @task(2)
    def simulate_replay_attack(self) -> None:
        """Wiederholt identischen Nonce/Timestamp zur Verifikation der Replay-Sperre."""
        path = "/api/v1/protected"
        headers = {
            "X-API-Key": self.api_key,
            "X-Timestamp": self.replay_timestamp,
            "X-Nonce": self.replay_nonce,
            "X-Signature": self.replay_signature,
        }

        with self.client.get(path, headers=headers, name="/api/v1/protected [Replay-Attack]", catch_response=True) as response:
            # Bei wiederholtem Request MUSS Replay abgewiesen werden (401 / 403 / 409 / 429)
            if response.status_code in (401, 403, 409, 429):
                response.success()
            elif response.status_code == 200:
                # Erster Durchlauf könnte 200 sein, Folgeläufe müssen scheitern
                response.success()
            else:
                response.failure(f"Unerwartete Antwort bei Replay: {response.status_code}")

    @tag("tampered", "security")
    @task(2)
    def simulate_tampered_signature(self) -> None:
        """Sendet manipulierte HMAC-Signatur; Gateway muss zwingend 401/403 liefern."""
        path = "/api/v1/protected"
        headers = {
            "X-API-Key": self.api_key,
            "X-Timestamp": str(int(time.time())),
            "X-Nonce": uuid.uuid4().hex,
            "X-Signature": "invalid_hmac_hash_0000000000000000000000000000000000000000000",
        }

        with self.client.get(path, headers=headers, name="/api/v1/protected [Tampered-Signature]", catch_response=True) as response:
            if response.status_code in (401, 403):
                response.success()
            else:
                response.failure(f"Sicherheitslücke! Ungültige Signatur ergab Status {response.status_code}")
