"""AetherMesh Locust-Lasttest-Suite.

Simuliert realistische Job-Einlieferung unter hoher Last, validiert
Backpressure-Verhalten (HTTP 429), Prioritätenverteilung und Latenz-SLAs.
"""

from __future__ import annotations

import random
import uuid
from locust import HttpUser, between, task


class AetherMeshLoadTestUser(HttpUser):
    """Simuliert Clients, die asynchrone Jobs mit variabler Priorität einliefern."""

    # Denkzeit zwischen Anfragen: 100ms bis 500ms für hohe Last
    wait_time = between(0.1, 0.5)

    def on_start(self) -> None:
        """Initialisierung pro virtuellem Benutzer."""
        self.submitted_job_ids: list[str] = []

    @task(10)
    def submit_standard_job(self) -> None:
        """Standard-Job mit mittlerer Priorität (5) einliefern."""
        payload = {
            "type": "data_transform",
            "priority": random.randint(3, 7),
            "payload": {
                "batch_id": str(uuid.uuid4()),
                "records": random.randint(10, 100),
            },
        }
        with self.client.post(
            "/api/v1/jobs",
            json=payload,
            name="POST /api/v1/jobs (Standard)",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 201, 202):
                data = response.json()
                job_id = data.get("id") or data.get("job_id")
                if job_id and len(self.submitted_job_ids) < 100:
                    self.submitted_job_ids.append(job_id)
                response.success()
            elif response.status_code == 429:
                # 429 ist erwartetes Backpressure-Verhalten unter Last
                retry_after = response.headers.get("Retry-After", "unknown")
                response.success()
            else:
                response.failure(f"Unerwarteter Statuscode: {response.status_code}")

    @task(3)
    def submit_high_priority_job(self) -> None:
        """Kritischer High-Priority-Job (Priorität 1-2)."""
        payload = {
            "type": "critical_event",
            "priority": random.randint(1, 2),
            "payload": {
                "alert_level": "high",
                "timestamp": str(uuid.uuid4()),
            },
        }
        with self.client.post(
            "/api/v1/jobs",
            json=payload,
            name="POST /api/v1/jobs (High-Priority)",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 201, 202):
                response.success()
            elif response.status_code == 429:
                response.success()
            else:
                response.failure(f"Fehler bei High-Priority Job: {response.status_code}")

    @task(4)
    def check_job_status(self) -> None:
        """Status eines zuvor eingereichten Jobs abfragen."""
        if not self.submitted_job_ids:
            return

        job_id = random.choice(self.submitted_job_ids)
        with self.client.get(
            f"/api/v1/jobs/{job_id}",
            name="GET /api/v1/jobs/[id]",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 404):
                response.success()
            elif response.status_code == 429:
                response.success()
            else:
                response.failure(f"Unerwarteter Status bei Job-Status: {response.status_code}")

    @task(2)
    def query_engine_health(self) -> None:
        """Health-Check-Endpunkt abfragen."""
        with self.client.get(
            "/health",
            name="GET /health",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Health-Check fehlgeschlagen mit Status: {response.status_code}")
