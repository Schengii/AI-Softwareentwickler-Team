import random

from locust import HttpUser, between, task


class SnippetVaultUser(HttpUser):
    """
    Lasttest für die Snippet-Vault API.
    Führt CRUD-Operationen und Suchanfragen aus.
    """
    wait_time = between(0.5, 2.0)

    def on_start(self):
        # Erstelle ein Test-Snippet für CRUD-Operationen
        self.snippet_id = None
        response = self.client.post("/api/snippets", json={
            "title": "Load Test Snippet",
            "code": "print('hello world')",
            "language": "python",
            "description": "Snippet für Lasttests"
        })
        if response.status_code == 201:
            self.snippet_id = response.json().get("id")

    @task(5)
    def list_snippets(self):
        self.client.get("/api/snippets")

    @task(3)
    def search_snippets(self):
        # Suche nach einem häufigen Begriff
        self.client.get("/api/snippets?q=python")

    @task(2)
    def get_snippet_detail(self):
        if self.snippet_id:
            self.client.get(f"/api/snippets/{self.snippet_id}")

    @task(1)
    def create_snippet(self):
        self.client.post("/api/snippets", json={
            "title": f"New Snippet {random.randint(1, 1000)}",
            "code": "pass",
            "language": "javascript",
            "description": "Auto-generiert"
        })
