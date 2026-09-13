"""ChronosPulse Locust Lasttest-Suite für 100 parallele Event-Producer.

Simuliert hochfrequente Event-Ingestion, Latenz- & CPU-Metriken,
Anomalie-Spikes und Webhook-Ereignisse gegen die ChronosPulse Plattform.
"""

from __future__ import annotations

import json
import random
import time
from typing import Any, Dict
from locust import HttpUser, TaskSet, between, events, tag, task
from locust.runners import MasterRunner, WorkerRunner


# Service-Pool für realistische verteilte Microservice-Topologie
SERVICES: list[str] = [
    "auth-service",
    "order-service",
    "payment-gateway",
    "inventory-api",
    "notification-worker",
    "telemetry-collector",
]

METRIC_NAMES: list[str] = [
    "http_request_duration_ms",
    "cpu_utilization_percent",
    "memory_rss_bytes",
    "active_db_connections",
    "queue_depth_count",
    "cache_hit_ratio",
]

ENVIRONMENTS: list[str] = ["prod-eu-west-1", "prod-eu-central-1", "stage-us-east-1"]


class EventProducerBehavior(TaskSet):
    """Szenario-Ablauf eines Event-Producers mit realistischer Lastverteilung."""

    @tag("ingest", "metrics")
    @task(10)
    def ingest_standard_metric(self) -> None:
        """Sendet Standard-Telemetriedaten mit niedrigem Overhead (hohe Frequenz)."""
        service = random.choice(SERVICES)
        metric_name = random.choice(METRIC_NAMES)
        
        # Normale Betriebswerte (z. B. 20-300ms Latenz, 15-80% CPU)
        if "duration" in metric_name or "latency" in metric_name:
            value = round(random.gauss(120.0, 30.0), 2)
            value = max(5.0, value)
        elif "percent" in metric_name:
            value = round(min(100.0, max(0.0, random.gauss(45.0, 15.0))), 2)
        else:
            value = round(random.uniform(10.0, 500.0), 2)

        payload: Dict[str, Any] = {
            "metric_name": metric_name,
            "value": value,
            "service": service,
            "timestamp": time.time(),
            "tags": {
                "env": random.choice(ENVIRONMENTS),
                "producer_id": f"worker-{self.user.producer_uuid[:8]}",
                "region": "eu-central-1",
            },
        }

        with self.client.post(
            "/api/v1/metrics",
            json=payload,
            headers={"Content-Type": "application/json"},
            name="/api/v1/metrics [Ingest Standard]",
            catch_response=True,
        ) as response:
            if response.status_code == 201:
                response.success()
            else:
                response.failure(
                    f"Metric Ingest fehlgeschlagen mit Status {response.status_code}: {response.text}"
                )

    @tag("ingest", "anomaly_spike")
    @task(1)
    def ingest_anomaly_spike_metric(self) -> None:
        """Erzeugt gezielte Anomalie-Spikes (>1000ms Latenz) zur Validierung der Incident-Detection."""
        service = random.choice(SERVICES)
        spike_value = round(random.uniform(1200.0, 4800.0), 2)

        payload: Dict[str, Any] = {
            "metric_name": "http_request_duration_ms",
            "value": spike_value,
            "service": service,
            "timestamp": time.time(),
            "tags": {
                "env": "prod-eu-west-1",
                "producer_id": f"spike-{self.user.producer_uuid[:8]}",
                "incident_trigger": "chaos_experiment",
            },
        }

        with self.client.post(
            "/api/v1/metrics",
            json=payload,
            headers={"Content-Type": "application/json"},
            name="/api/v1/metrics [Ingest Spike/Anomaly]",
            catch_response=True,
        ) as response:
            if response.status_code == 201:
                response.success()
            else:
                response.failure(f"Anomaly Spike Ingestion fehlgeschlagen: {response.text}")

    @tag("ingest", "webhooks")
    @task(2)
    def send_external_webhook(self) -> None:
        """Simuliert eintreffende Alertmanager/PagerDuty Webhook-Benachrichtigungen."""
        service = random.choice(SERVICES)
        payload: Dict[str, Any] = {
            "event_type": "alert.threshold_breached",
            "source": f"locust-producer-{service}",
            "payload": {
                "severity": random.choice(["warning", "critical"]),
                "threshold": 90.0,
                "current_value": round(random.uniform(91.0, 99.5), 2),
                "affected_host": f"node-{random.randint(1, 20)}.cluster.local",
            },
            "secret": "chronos-load-test-token",
            "timestamp": time.time(),
        }

        with self.client.post(
            "/api/v1/webhooks",
            json=payload,
            headers={"Content-Type": "application/json"},
            name="/api/v1/webhooks [Inbound Event]",
            catch_response=True,
        ) as response:
            if response.status_code == 201:
                response.success()
            else:
                response.failure(f"Webhook Ingestion fehlgeschlagen: {response.text}")

    @tag("query", "telemetry")
    @task(3)
    def query_recent_metrics(self) -> None:
        """Liest kürzliche Metriken aus (simuliert Monitoring-Dashboard-Consumer)."""
        service = random.choice(SERVICES)
        limit = random.choice([10, 25, 50])
        params = {"service": service, "limit": limit}

        with self.client.get(
            "/api/v1/metrics",
            params=params,
            name="/api/v1/metrics [Query History]",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Query Metrics fehlgeschlagen: {response.status_code}")

    @tag("query", "anomalies")
    @task(1)
    def query_anomalies(self) -> None:
        """Fragt aktive Anomalien ab (simuliert Incident-Operator / Dashboard)."""
        with self.client.get(
            "/api/v1/anomalies",
            params={"limit": 20, "acknowledged": False},
            name="/api/v1/anomalies [Query Unacknowledged]",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Query Anomalies fehlgeschlagen: {response.status_code}")


class ChronosPulseEventProducer(HttpUser):
    """Locust HttpUser-Klasse für parallele Event-Producer.
    
    Konzipiert für Lasttests mit 100 Usern (z. B. `locust -u 100 -r 20 --headless -t 60s`).
    Nutzt relative Pfade; Basis-URL wird per `--host` übergeben.
    """

    # Kurze Denkzeit zwischen den Requests (10ms bis 50ms = hoher Durchsatz)
    wait_time = between(0.01, 0.05)
    tasks = [EventProducerBehavior]

    def on_start(self) -> None:
        """Initialisierung jedes virtuellen Producers."""
        import uuid
        self.producer_uuid: str = str(uuid.uuid4())
        # Optionaler Handshake / Health-Check zum Teststart
        with self.client.get(
            "/api/v1/metrics",
            params={"limit": 1},
            name="/api/v1/metrics [Warmup]",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 404):
                resp.success()


# Optional: Hook für Lasttest-Reporting Metriken & SLAs
@events.test_stop.add_listener
def on_test_stop(environment: Any, **kwargs: Any) -> None:
    """Validiere SLAs beim Abschluss des Lasttests."""
    if isinstance(environment.runner, (MasterRunner, WorkerRunner)):
        return

    stats = environment.runner.stats.total
    fail_ratio = stats.fail_ratio
    p95 = stats.get_response_time_percentile(0.95)
    avg_rps = stats.total_rps

    print("\n=======================================================")
    print(" 🏁 CHRONOSPULSE LOAD-TEST ERGEBNISSE & SLA-BERICHT")
    print("=======================================================")
    print(f" Gesamt-Requests : {stats.num_requests}")
    print(f" Fehlerrate      : {fail_ratio * 100:.2f}% (Ziel: < 0.1%)")
    print(f" P95 Latenz      : {p95:.2f} ms (Ziel: < 200 ms)")
    print(f" Durchsatz       : {avg_rps:.2f} Requests/s")
    print("=======================================================\n")
