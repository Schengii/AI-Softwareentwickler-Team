import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Minimaler Health-Check für den Smoke-Test
app = FastAPI()

@app.get("/health")
async def health():
    return {"status": "ok"}

@pytest.fixture
def client():
    return TestClient(app)

def test_app_starts_and_health_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
