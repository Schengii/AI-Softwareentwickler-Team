import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

def test_idempotency_key_header_required():
    """Testet, dass der Idempotency-Key Header für Sagas erforderlich ist."""
    with TestClient(app) as client:
        response = client.post("/api/v1/sagas", json={"workflow_type": "order", "payload": {}})
        assert response.status_code == 422 

def test_saga_creation_with_idempotency_key():
    """Testet die Erstellung einer Saga mit Idempotency-Key."""
    key = str(uuid.uuid4())
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/sagas", 
            json={"workflow_type": "order", "payload": {"item": "test"}},
            headers={"Idempotency-Key": key}
        )
        assert response.status_code in [200, 201]

def test_idempotency_replay():
    """Testet, dass bei gleichem Key das Ergebnis repliziert wird."""
    key = str(uuid.uuid4())
    payload = {"workflow_type": "order", "payload": {"item": "test"}}
    
    with TestClient(app) as client:
        res1 = client.post("/api/v1/sagas", json=payload, headers={"Idempotency-Key": key})
        assert res1.status_code in [200, 201]
        
        res2 = client.post("/api/v1/sagas", json=payload, headers={"Idempotency-Key": key})
        assert res2.status_code == 200
        assert res2.json() == res1.json()
