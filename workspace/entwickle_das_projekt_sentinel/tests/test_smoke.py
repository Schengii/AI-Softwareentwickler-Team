from fastapi import FastAPI
from fastapi.testclient import TestClient

# Da die App noch nicht existiert, erstellen wir ein minimales Gerüst für den Smoke-Test
app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}

client = TestClient(app)

def test_app_starts_and_health_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
