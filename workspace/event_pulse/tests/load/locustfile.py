import uuid

from locust import HttpUser, between, task


class EventPulseUser(HttpUser):
    wait_time = between(0.1, 0.5)

    @task(3)
    def ingest_event(self):
        payload = {
            "event_type": "user.signup",
            "payload": {"user_id": str(uuid.uuid4()), "email": "test@example.com"}
        }
        self.client.post(
            "/api/v1/events",
            json=payload,
            headers={"Content-Type": "application/json"}
        )

    @task(1)
    def list_events(self):
        self.client.get("/api/v1/events")
