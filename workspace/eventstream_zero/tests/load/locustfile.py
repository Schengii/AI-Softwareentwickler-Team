import random
import uuid

from locust import HttpUser, between, task


class EventStreamZeroUser(HttpUser):
    """
    Lasttest für EventStream-Zero:
    - Publizieren von Nachrichten
    - Abrufen von Nachrichten
    - Monitoring-Endpunkte
    """
    wait_time = between(0.1, 0.5)

    def on_start(self):
        self.topic = f"test_topic_{uuid.uuid4().hex[:8]}"
        self.client.post("/api/v1/topics", json={"name": self.topic})

    @task(3)
    def publish_message(self):
        payload = {
            "data": "sensor_data_point",
            "value": random.random() * 100,
            "correlation_id": str(uuid.uuid4())
        }
        self.client.post(f"/api/v1/topics/{self.topic}/publish", json=payload)

    @task(2)
    def get_messages(self):
        self.client.get(f"/api/v1/topics/{self.topic}/messages")

    @task(1)
    def get_metrics(self):
        self.client.get("/metrics")
