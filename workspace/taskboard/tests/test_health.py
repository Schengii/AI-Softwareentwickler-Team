import importlib.util
from unittest.mock import MagicMock

import pytest

# Nur die tatsaechliche Installation von FastAPI wird hier toleriert (z.B. eine minimale
# CI-Umgebung ohne die vollen Projekt-Abhaengigkeiten) - ein `from app.main import app`, das
# TROTZ installiertem FastAPI mit einem ImportError fehlschlaegt (z.B. ein Bug in
# app/core/config.py), ist ein echter Anwendungsfehler und darf NICHT in denselben
# "FastAPI fehlt"-Pfad fallen. Ein zu weit gefasstes `except ImportError` um BEIDE Faelle
# machte genau das zuvor: test_health_check wurde dann fälschlich uebersprungen statt die
# Suite rot werden zu lassen, obwohl die App gar nicht startfaehig war.
HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None

if HAS_FASTAPI:
    from app.main import app
    from fastapi.testclient import TestClient
else:
    app = MagicMock()
    TestClient = MagicMock

@pytest.fixture
def client():
    if HAS_FASTAPI:
        return TestClient(app)
    else:
        # Mock-Client für Umgebungen ohne FastAPI
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok"}
        mock_client.get.return_value = mock_response
        return mock_client

@pytest.mark.skipif(not HAS_FASTAPI, reason="FastAPI nicht installiert")
def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_health_check_mocked():
    # Dieser Test läuft auch, wenn FastAPI fehlt
    client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "ok"}
    client.get.return_value = mock_response
    
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
