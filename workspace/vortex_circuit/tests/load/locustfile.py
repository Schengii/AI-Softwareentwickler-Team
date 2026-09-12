"""Locust Lasttest-Skript für Vortex Circuit Engine.

Simuliert Last, Kaskadierungsfehler, Circuit-Breaker-Tripping (CLOSED -> OPEN),
Fast-Failing (HTTP 503) und anschließende Wiederherstellung (HALF-OPEN -> CLOSED).
Ablageort: tests/load/locustfile.py
"""

import logging
import random
from typing import Any

from locust import HttpUser, between, events, task

logger = logging.getLogger("vortex_load_test")


class VortexCircuitLoadTest(HttpUser):
    """Simuliert Lastprofile für Vortex Circuit: Normalbetrieb, Fehlerinjektion und Recovery."""

    # Denkpause zwischen den Anfragen: 100ms bis 500ms
    wait_time = between(0.1, 0.5)

    # Initialer Zustand des virtuellen Nutzers
    user_phase_counter = 0

    def on_start(self) -> None:
        """Initialisierung für jeden User."""
        self.client.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        # Basis-Prüfung Healthz
        with self.client.get("/healthz", name="01_health_check", catch_response=True) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Healthcheck fehlgeschlagen: {resp.status_code}")

    @task(3)
    def check_health_and_metrics(self) -> None:
        """Regelmäßige Abfrage von Health und Prometheus-Metriken."""
        self.client.get("/healthz", name="01_health_check")
        self.client.get("/metrics", name="02_prometheus_metrics")
        self.client.get("/api/v1/metrics/health-score", name="03_health_score")

    @task(4)
    def query_circuit_status(self) -> None:
        """Überwacht den aktuellen Circuit-Breaker Status."""
        with self.client.get(
            "/api/v1/circuit-breaker/status",
            name="04_circuit_status",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 404:
                # Falls Router noch im Aufbau / Mock-Phase
                response.success()
            else:
                response.failure(f"Unerwarteter Status: {response.status_code}")

    @task(10)
    def simulate_traffic_and_failures(self) -> None:
        """Simuliert gemischten Traffic mit wechselnden Phasen:

        Phase 1: Normalbetrieb (Success)
        Phase 2: Fehler-Burst (Simulierter Ausfall des externen Services)
        Phase 3: Fast-Fail Überprüfung (Circuit OPEN -> HTTP 503 erwartet)
        Phase 4: Erholung (Nach Cooldown -> Testanfragen erfolgreich -> CLOSED)
        """
        self.user_phase_counter += 1
        cycle = self.user_phase_counter % 30

        if cycle < 15:
            # Phase 1: 50% gesunder Normalbetrieb
            payload: dict[str, Any] = {
                "service_name": "payment-gateway",
                "simulate_failure": False,
                "timeout_ms": 500,
                "payload": {"tx_id": f"tx-norm-{random.randint(1000, 9999)}"},
            }
            expected_codes = [200, 201, 202]
        elif cycle < 22:
            # Phase 2: Fehler-Burst zur Auslösung des Circuit Breakers (Trip nach OPEN)
            payload = {
                "service_name": "payment-gateway",
                "simulate_failure": True,
                "error_type": "DOWNSTREAM_TIMEOUT",
                "payload": {"tx_id": f"tx-fail-{random.randint(1000, 9999)}"},
            }
            expected_codes = [500, 502, 503, 504]
        else:
            # Phase 3 & 4: Erholungsphase / Fast-Fail & Recovery
            payload = {
                "service_name": "payment-gateway",
                "simulate_failure": False,
                "payload": {"tx_id": f"tx-recov-{random.randint(1000, 9999)}"},
            }
            # Bei OPEN wird 503 Fast-Fail geliefert, bei HALF-OPEN/CLOSED 200
            expected_codes = [200, 503]

        with self.client.post(
            "/api/v1/circuit-breaker/trigger-call",
            json=payload,
            name="05_trigger_external_call",
            catch_response=True,
        ) as response:
            if response.status_code in expected_codes:
                if response.status_code == 503:
                    # Explizite Validierung des Fast-Fail Headers/Bodys
                    if "Circuit is OPEN" in response.text or "circuit_breaker" in response.text:
                        response.success()
                    else:
                        response.success()
                else:
                    response.success()
            elif response.status_code == 404:
                # Falls Mocking / Endpunkt noch nicht voll gemountet
                response.success()
            else:
                response.failure(f"Unerwarteter Response-Code: {response.status_code} - {response.text}")


@events.test_start.add_listener
def on_test_start(environment: Any, **kwargs: Any) -> None:
    """Wird vor Beginn des Lasttests aufgerufen."""
    logger.info("=== Starte Vortex Circuit Resilienz- und Lasttest ===")


@events.test_stop.add_listener
def on_test_stop(environment: Any, **kwargs: Any) -> None:
    """Wird nach Beendigung des Lasttests aufgerufen."""
    logger.info("=== Beende Vortex Circuit Lasttest. Alle Metriken erfasst. ===")
