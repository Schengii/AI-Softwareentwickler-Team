"""
Lasttest-Skript für das PulseFlow Gateway (Locust).

Ziel: Mind. 100 parallele Event-Ingestions (Webhook-POSTs) sowie
parallele Event-Listing-Requests. Auswertung von p95/p99-Latenzen
erfolgt über die Locust-eigenen Statistiken (--csv Export) bzw.
das Web-UI / Headless-Report.

Ausführung (Beispiel):
    locust -f tests/load/locustfile.py --host http://127.0.0.1:8000 \
           --users 150 --spawn-rate 20 --run-time 2m --headless \
           --csv=tests/load/report

Die Host-URL wird von Locust selbst über --host injiziert (siehe
core/verifier.py.check_load_test()) - daher NIEMALS hart codieren.

p95/p99 Auswertung:
    Locust schreibt bei --csv=<prefix> u.a. <prefix>_stats.csv mit
    Spalten "95%" und "99%" (Antwortzeiten in ms) pro Endpoint sowie
    "Aggregated". Alternativ liefert der Headless-Run am Ende eine
    Tabelle mit Percentile-Verteilung direkt in stdout.
"""
import hashlib
import hmac
import json

# Gemeinsames Secret für HMAC-SHA256 Signatur-Validierung.
# Muss mit dem im Gateway konfigurierten Test-/Demo-Secret für die
# jeweilige source_id übereinstimmen (siehe app/config.py bzw. ENV
# WEBHOOK_SECRET_<SOURCE_ID>). Über --host-unabhängige ENV Variable
# steuerbar, damit der Lasttest gegen unterschiedliche Umgebungen mit
# unterschiedlichen Secrets laufen kann.
import os
import random
import string
import time
import uuid

from locust import HttpUser, between, events, task

WEBHOOK_SECRET = os.environ.get("PULSEFLOW_WEBHOOK_SECRET", "test-secret-please-rotate")
SOURCE_IDS = ["github", "stripe"]

EVENT_STATUSES = ["pending", "processed", "failed", "dlq"]


def _sign_payload(secret: str, raw_body: bytes) -> str:
    """Berechnet die HMAC-SHA256-Signatur für den Webhook-Body."""
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _random_github_push_payload() -> dict:
    """Erzeugt ein realistisches GitHub-Push-artiges Event-Payload."""
    return {
        "ref": "refs/heads/main",
        "repository": {"id": random.randint(1, 999999), "full_name": "acme/pulseflow-demo"},
        "pusher": {"name": "".join(random.choices(string.ascii_lowercase, k=8))},
        "commits": [
            {
                "id": uuid.uuid4().hex,
                "message": "load-test commit",
                "timestamp": time.time(),
            }
        ],
    }


def _random_stripe_event_payload() -> dict:
    """Erzeugt ein realistisches Stripe-Event-artiges Payload."""
    return {
        "id": f"evt_{uuid.uuid4().hex[:24]}",
        "type": random.choice(["charge.succeeded", "invoice.paid", "charge.failed"]),
        "data": {
            "object": {
                "amount": random.randint(100, 500000),
                "currency": "eur",
                "id": f"ch_{uuid.uuid4().hex[:24]}",
            }
        },
        "created": int(time.time()),
    }


class WebhookIngestionUser(HttpUser):
    """
    Simuliert Drittanbieter (GitHub/Stripe), die Webhooks einreichen.
    Fokus: Durchsatz & Latenz von POST /api/v1/webhooks/{source_id}
    inkl. gültiger HMAC-Signatur und Idempotency-Key.
    """

    # Kurze Wartezeit -> hoher Durchsatz, simuliert Burst-Traffic von
    # mehreren Drittanbieter-Systemen gleichzeitig.
    wait_time = between(0.05, 0.3)
    weight = 3  # Ingestion ist der dominante Traffic-Anteil

    @task(5)
    def post_webhook_github(self):
        self._post_webhook("github", _random_github_push_payload())

    @task(5)
    def post_webhook_stripe(self):
        self._post_webhook("stripe", _random_stripe_event_payload())

    @task(1)
    def post_webhook_duplicate(self):
        """
        Sendet denselben Idempotency-Key zweimal hintereinander, um
        den Idempotenz-Pfad (erwartete 200/409 ohne Doppel-Processing)
        unter Last mitzumessen.
        """
        source_id = random.choice(SOURCE_IDS)
        payload = _random_github_push_payload() if source_id == "github" else _random_stripe_event_payload()
        idem_key = str(uuid.uuid4())
        self._post_webhook(source_id, payload, idempotency_key=idem_key, name_suffix="_dup_1")
        self._post_webhook(source_id, payload, idempotency_key=idem_key, name_suffix="_dup_2")

    def _post_webhook(self, source_id: str, payload: dict, idempotency_key: str | None = None, name_suffix: str = ""):
        body_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        signature = _sign_payload(WEBHOOK_SECRET, body_bytes)
        headers = {
            "Content-Type": "application/json",
            "X-Pulse-Signature": signature,
            "Idempotency-Key": idempotency_key or str(uuid.uuid4()),
        }
        with self.client.post(
            f"/api/v1/webhooks/{source_id}",
            data=body_bytes,
            headers=headers,
            name=f"/api/v1/webhooks/{source_id}{name_suffix}",
            catch_response=True,
        ) as response:
            # 200/201/202 = akzeptiert; 409 = erwartetes Idempotenz-Duplikat
            if response.status_code in (200, 201, 202, 409):
                response.success()
            else:
                response.failure(f"Unerwarteter Status: {response.status_code} - {response.text[:200]}")


class DashboardApiUser(HttpUser):
    """
    Simuliert Dashboard-Clients, die Event-Listen, Metriken abfragen
    und gelegentlich DLQ-Retries auslösen.
    """

    wait_time = between(0.5, 2.0)
    weight = 1

    @task(6)
    def list_events(self):
        page = random.randint(1, 5)
        page_size = random.choice([20, 50, 100])
        status_filter = random.choice(EVENT_STATUSES + [None])
        params = {"page": page, "page_size": page_size}
        if status_filter:
            params["status"] = status_filter
        with self.client.get(
            "/api/v1/events",
            params=params,
            name="/api/v1/events",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Unerwarteter Status: {response.status_code}")

    @task(3)
    def get_metrics(self):
        with self.client.get(
            "/api/v1/metrics",
            name="/api/v1/metrics",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Unerwarteter Status: {response.status_code}")

    @task(1)
    def retry_dlq_event(self):
        """
        Löst manuelles Re-Triggering aus der DLQ aus. Da die
        Event-ID unter Lasttest-Bedingungen meist nicht existiert,
        wird 404 als erwartetes (kein Fehler-)Ergebnis gewertet - der
        Endpoint selbst und dessen Latenz stehen hier im Fokus, nicht
        die fachliche Korrektheit des Retries.
        """
        fake_event_id = random.randint(1, 100000)
        with self.client.post(
            f"/api/v1/events/retry/{fake_event_id}",
            name="/api/v1/events/retry/[id]",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 202, 404, 409):
                response.success()
            else:
                response.failure(f"Unerwarteter Status: {response.status_code}")

    @task(1)
    def health_check(self):
        with self.client.get("/health", name="/health", catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Unerwarteter Status: {response.status_code}")


@events.quitting.add_listener
def _check_slo_on_exit(environment, **kwargs):
    """
    Prüft nach Testende die aggregierten p95/p99-Latenzen gegen ein
    SLA-Ziel und setzt den Exit-Code auf 1, falls verletzt.

    SLA-Ziel: p95 < 500ms, p99 < 1000ms für den Webhook-Ingestion-Pfad
    (dominanter, kritischer Pfad des Gateways).
    """
    stats = environment.stats.total
    p95 = stats.get_response_time_percentile(0.95)
    p99 = stats.get_response_time_percentile(0.99)
    error_rate = (stats.num_failures / stats.num_requests) if stats.num_requests else 0

    print("\n=== SLA-Auswertung (Gesamt) ===")
    print(f"Requests gesamt: {stats.num_requests}, Fehler: {stats.num_failures} ({error_rate:.2%})")
    print(f"p95: {p95} ms | p99: {p99} ms")

    SLA_P95_MS = 500
    SLA_P99_MS = 1000
    SLA_MAX_ERROR_RATE = 0.01

    violations = []
    if p95 and p95 > SLA_P95_MS:
        violations.append(f"p95 {p95}ms > SLA {SLA_P95_MS}ms")
    if p99 and p99 > SLA_P99_MS:
        violations.append(f"p99 {p99}ms > SLA {SLA_P99_MS}ms")
    if error_rate > SLA_MAX_ERROR_RATE:
        violations.append(f"Error-Rate {error_rate:.2%} > SLA {SLA_MAX_ERROR_RATE:.0%}")

    if violations:
        print("SLA VERLETZT: " + "; ".join(violations))
        environment.process_exit_code = 1
    else:
        print("SLA eingehalten.")
