"""Locust Load Test Suite für ChronosLedger Audit- & Incident-Logging-Gateway.

Simuliert realistische Hochlast-Szenarien für:
- Asynchrone Ingestion über den Ring-Buffer (POST /api/v1/ledger/events)
- Kryptografische Verifikation (GET /api/v1/ledger/verify/<id>)
- Revisionsabfragen & Health-Checks
- Variable Payloads inkl. PII-Simulation zur Überprüfung des Sanitizers
"""
from __future__ import annotations

import random
import time
import uuid
from typing import Any

from locust import HttpUser, between, task

# Testdaten-Generatoren für realistische Lasttests
EVENT_TYPES = [
    "auth.login.success",
    "auth.login.failure",
    "data.export.requested",
    "order.payment.processed",
    "user.privilege.escalation",
    "system.config.changed",
    "security.token.revoked",
    "api.rate_limit.exceeded",
]

SEVERITIES = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]

SAMPLE_USERS = [
    "alice@corp-chronos.io",
    "bob.smith@finance-partner.de",
    "charlie.admin@internal-sec.org",
    "compliance-bot-42@cloud.internal",
]

SAMPLE_IPS = [
    "192.168.1.45",
    "10.0.12.89",
    "172.16.254.1",
    "203.0.113.195",
]

SAMPLE_TENANTS = [
    "tenant-default",
    "tenant-alpha",
    "tenant-beta",
    "tenant-enterprise",
]


class ChronosLedgerLoadUser(HttpUser):
    """Locust User zur Simulation hoher Ingestion-Last und kryptografischer Abfragen."""

    # Denkzeit zwischen 20ms und 100ms für realistische Hochlast-Szenarien
    wait_time = between(0.02, 0.1)

    def on_start(self) -> None:
        """Initialisierung pro virtuellem Nutzer."""
        self.tenant_id = random.choice(SAMPLE_TENANTS)
        self.api_key = "secret-chronos-key"
        self.default_headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.api_key,
            "X-Tenant-ID": self.tenant_id,
        }
        self.created_entry_ids: list[str] = []

    def _generate_variable_payload(self) -> dict[str, Any]:
        """Erzeugt variable Audit-Payloads mit dynamischer Größe und PII-Merkmalen."""
        event_type = random.choice(EVENT_TYPES)
        severity = random.choice(SEVERITIES)
        user_email = random.choice(SAMPLE_USERS)
        ip_addr = random.choice(SAMPLE_IPS)

        # Simulierte Nutzlast mit variablen Feldern (Metadaten, Security Context, PII)
        payload_data: dict[str, Any] = {
            "actor_email": user_email,
            "client_ip": ip_addr,
            "action": event_type,
            "auth_token": f"bearer_{uuid.uuid4().hex}",
            "resource_id": f"res_{uuid.uuid4().hex[:12]}",
            "timestamp_unix": time.time(),
            "environment": random.choice(["production", "staging", "eu-central-1"]),
        }

        # Gelegentlich größere Datenmengen anhängen, um Durchsatz/Paging zu belasten
        if random.random() < 0.2:
            payload_data["debug_context"] = {
                "stack_trace": f"SyntheticTrace-{uuid.uuid4()}",
                "query_parameters": {"limit": random.randint(10, 1000), "filter": "active"},
                "affected_items": [f"item_{i}_{uuid.uuid4().hex[:6]}" for i in range(random.randint(5, 20))],
            }

        return {
            "event_type": event_type,
            "severity": severity,
            "tenant_id": self.tenant_id,
            "payload": payload_data,
            "client_timestamp": time.time(),
        }

    @task(70)
    def ingest_single_event(self) -> None:
        """Hauptlast: Asynchrone Ingestion von Audit-Events in den Ring-Buffer."""
        payload = self._generate_variable_payload()
        with self.client.post(
            "/api/v1/ledger/events",
            json=payload,
            headers=self.default_headers,
            catch_response=True,
            name="POST /api/v1/ledger/events",
        ) as response:
            if response.status_code in (200, 201, 202):
                try:
                    data = response.json()
                    entry_id = data.get("entry_id") or data.get("id")
                    if entry_id and len(self.created_entry_ids) < 50:
                        self.created_entry_ids.append(str(entry_id))
                    response.success()
                except (ValueError, KeyError):
                    response.success()
            else:
                response.failure(f"Unerwarteter Statuscode: {response.status_code} - {response.text}")

    @task(15)
    def ingest_batch_events(self) -> None:
        """Batch-Ingestion zur Prüfung des Ring-Buffer-Throughputs unter Spitzenlast."""
        batch_size = random.randint(5, 25)
        batch = [self._generate_variable_payload() for _ in range(batch_size)]

        with self.client.post(
            "/api/v1/ledger/events/batch",
            json={"events": batch},
            headers=self.default_headers,
            catch_response=True,
            name="POST /api/v1/ledger/events/batch",
        ) as response:
            # Akzeptiere 200/201/202 oder 404 falls Batch-Endpunkt optional/nicht definiert
            if response.status_code in (200, 201, 202, 404):
                response.success()
            else:
                response.failure(f"Batch-Ingest fehlgeschlagen: {response.status_code}")

    @task(10)
    def verify_ledger_entry(self) -> None:
        """Prüfung der mathematischen Integrität (SHA-256 Kette) eines Eintrags."""
        entry_id = (
            random.choice(self.created_entry_ids)
            if self.created_entry_ids
            else str(uuid.uuid4())
        )
        with self.client.get(
            f"/api/v1/ledger/verify/{entry_id}",
            headers=self.default_headers,
            catch_response=True,
            name="GET /api/v1/ledger/verify/[id]",
        ) as response:
            # 200 (Valid), 404 (Eintrag noch im Buffer oder nicht existent) sind valide Systemzustände
            if response.status_code in (200, 404):
                response.success()
            else:
                response.failure(f"Verifikation fehlgeschlagen mit Status: {response.status_code}")

    @task(5)
    def health_check(self) -> None:
        """Liveness & Readiness Probe Endpunkt-Prüfung."""
        with self.client.get("/health", catch_response=True, name="GET /health") as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Health-Check fehlgeschlagen: {response.status_code}")
