from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app
from src.api_integration.schemas import SASTReport

client = TestClient(app)

@pytest.mark.asyncio
async def test_run_audit_success():
    """Testet den erfolgreichen Start einer Sicherheitsanalyse."""
    mock_report = SASTReport(
        tool="bandit",
        total_issues=0,
        issues=[],
        status="success"
    )
    
    with patch("src.api_integration.sast_adapter.SASTAdapter.run_analysis", return_value=mock_report):
        response = client.post(
            "/api/v1/audit/run",
            json={"repo_url": "/tmp/test", "scan_type": "bandit"}
        )
        
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert "audit_id" in data
    assert data["report"]["tool"] == "bandit"

@pytest.mark.asyncio
async def test_run_audit_failure():
    """Testet das Verhalten bei einem Adapter-Fehler."""
    with patch("src.api_integration.sast_adapter.SASTAdapter.run_analysis", side_effect=Exception("Analysis failed")):
        response = client.post(
            "/api/v1/audit/run",
            json={"repo_url": "/tmp/test", "scan_type": "bandit"}
        )
        
    assert response.status_code == 500
    assert "detail" in response.json()
