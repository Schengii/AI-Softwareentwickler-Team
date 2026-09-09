from locust import HttpUser, between, task


class GovernancePlatformUser(HttpUser):
    """
    Lasttest für die Autonome Multi-Agenten-Governance & Code-Inspection-Plattform.
    Ziel: >= 50 gleichzeitige Nutzer.
    """
    wait_time = between(0.5, 2.0)

    @task(3)
    def get_analysis_status(self):
        # Beispielhafter Endpunkt für Statusabfragen
        self.client.get("/api/v1/analysis/123", name="/api/v1/analysis/[id]")

    @task(1)
    def upload_code(self):
        # Beispielhafter Endpunkt für Code-Uploads
        self.client.post("/api/v1/upload", json={"project_id": "test", "code": "print('hello')"})

    @task(1)
    def login(self):
        # Beispielhafter Endpunkt für Auth
        self.client.post("/api/v1/auth/login", json={"username": "admin", "password": "password"})
