from locust import HttpUser, task, between

class AnalyticsUser(HttpUser):
    wait_time = between(0.5, 2.0)

    @task(3)
    def get_tasks(self):
        self.client.get("/api/tasks")

    @task(2)
    def get_metrics(self):
        self.client.get("/api/metrics")

    @task(1)
    def create_task(self):
        self.client.post("/api/tasks", json={
            "title": "Load Test Task",
            "description": "Task created by Locust",
            "status": "pending"
        })

    @task(1)
    def create_metric(self):
        self.client.post("/api/metrics", json={
            "metric_name": "response_time",
            "value": 123.45,
            "notes": "Automated test metric"
        })
