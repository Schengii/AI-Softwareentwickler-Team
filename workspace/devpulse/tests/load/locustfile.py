from locust import HttpUser, between, task


class DevPulseUser(HttpUser):
    wait_time = between(1, 3)

    @task(3)
    def get_projects(self):
        self.client.get("/api/v1/projects")

    @task(2)
    def get_sessions(self):
        self.client.get("/api/v1/sessions")

    @task(1)
    def create_project(self):
        self.client.post("/api/v1/projects", json={
            "name": "Test Project",
            "description": "Load test project"
        })

    @task(1)
    def create_session(self):
        # Assuming project ID 1 exists for testing
        self.client.post("/api/v1/sessions", json={
            "project_id": 1,
            "note": "Load test session"
        })
