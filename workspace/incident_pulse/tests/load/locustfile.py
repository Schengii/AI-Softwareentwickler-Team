"""Locust-Lasttestsuite für IncidentPulse REST-API und SSE-Verbindungen."""

import random
import time

from locust import HttpUser, between, task


class IncidentPulseUser(HttpUser):
    """Simuliert Anwender und Operatoren, die das Dashboard nutzen,

    Incidents erstellen, abfragen, Metriken laden und SSE-Events konsumieren.
    """

    wait_time = between(1.0, 3.0)

    def on_start(self) -> None:
        """Initialisierung vor Beginn der Tasks: Erstellt ggf. Basisdaten."""
        self.created_incident_ids: list[int] = []

    @task(4)
    def get_dashboard_static(self) -> None:
        """Lädt die statische SPA-Startseite."""
        self.client.get("/", name="Frontend: Dashboard SPA")

    @task(6)
    def list_incidents(self) -> None:
        """Fragt die Liste aller Incidents ab."""
        self.client.get("/api/v1/incidents", name="REST: List Incidents")

    @task(3)
    def get_metrics(self) -> None:
        """Fragt Dashboard-Metriken (MTTR, aktive Incidents, Services) ab."""
        self.client.get("/api/v1/metrics", name="REST: Get Metrics")

    @task(2)
    def create_incident(self) -> None:
        """Erstellt einen neuen Incident mit zufälligem Schweregrad."""
        severities = ["low", "medium", "high", "critical"]
        payload = {
            "title": f"LoadTest Incident {random.randint(1000, 99999)}",
            "description": "Automatisch generierter Incident im Rahmen des Lasttests.",
            "severity": random.choice(severities),
            "status": "investigating",
            "tags": ["loadtest", "simulated"],
        }
        headers = {"Content-Type": "application/json"}
        response = self.client.post(
            "/api/v1/incidents",
            json=payload,
            headers=headers,
            name="REST: Create Incident",
        )
        if response.status_code in (200, 201):
            try:
                data = response.json()
                if "id" in data:
                    self.created_incident_ids.append(data["id"])
                    # Maximal 20 IDs lokal vorhalten
                    if len(self.created_incident_ids) > 20:
                        self.created_incident_ids.pop(0)
            except Exception:
                pass

    @task(3)
    def get_incident_detail(self) -> None:
        """Liest Detailinformationen zu einem existierenden Incident."""
        if self.created_incident_ids:
            incident_id = random.choice(self.created_incident_ids)
            self.client.get(
                f"/api/v1/incidents/{incident_id}",
                name="REST: Get Incident Details",
            )
        else:
            self.client.get("/api/v1/incidents/1", name="REST: Get Incident Details (ID=1)")

    @task(1)
    def stream_sse_events(self) -> None:
        """Simuliert eine Server-Sent Events (SSE) Verbindung für Live-Updates.

        Liest bis zu 3 Chunks oder bricht nach kurzer Dauer ab, um den
        Locust-Worker nicht dauerhaft zu blockieren.
        """
        start_time = time.time()
        endpoint = "/api/v1/incidents/events"
        try:
            with self.client.get(
                endpoint,
                stream=True,
                headers={"Accept": "text/event-stream"},
                name="SSE: Live Events Stream",
                catch_response=True,
                timeout=5.0,
            ) as response:
                if response.status_code == 200:
                    chunks_read = 0
                    # Stream-Chunks kurz auslesen und Verbindung danach sauber schließen
                    for line in response.iter_lines(chunk_size=1024):
                        if line:
                            chunks_read += 1
                        if chunks_read >= 2 or (time.time() - start_time) > 2.0:
                            break
                    response.success()
                else:
                    response.failure(f"Unerwarteter Statuscode: {response.status_code}")
        except Exception:  # noqa: BLE001 - Abfangen von Streaming-/Timeout-Events im Lasttest
            # Timeouts bei SSE-Streams sind je nach Testaufbau erwartbar
            pass
