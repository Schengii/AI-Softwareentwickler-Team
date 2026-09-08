from unittest.mock import AsyncMock, patch

import pytest

from app.schemas.ai_analysis import IncidentPayload
from app.services.ai_analyst import analyze_incident


@pytest.mark.asyncio
async def test_analyze_incident_resilience():
    # Teste, ob der Circuit Breaker bei Fehlern öffnet
    # Wir müssen den Breaker für den Test zurücksetzen, da er global ist
    from app.utils.resilience import ai_service_breaker
    ai_service_breaker.close()

    incident = IncidentPayload(
        incident_id="test",
        service_name="checkout-api",
        error_code="500",
        message="Internal Server Error",
    )

    with patch("app.services.ai_analyst.client.chat.completions.create", side_effect=Exception("API Down")):
        # Wir provozieren 3 Fehler, um den Breaker zu öffnen
        for _ in range(3):
            try:
                await analyze_incident(incident)
            except Exception:
                pass

        # Der 4. Aufruf sollte nun den Breaker auslösen und den typsicheren Fallback liefern
        result = await analyze_incident(incident)
        assert result.incident_id == "test"
        assert result.suggested_workflow["action"] == "manual_review_required"

@pytest.mark.asyncio
async def test_analyze_incident_retry():
    # Teste, ob Retry bei temporärem Fehler funktioniert
    from app.utils.resilience import ai_service_breaker
    ai_service_breaker.close()

    incident = IncidentPayload(
        incident_id="test",
        service_name="checkout-api",
        error_code="500",
        message="Internal Server Error",
    )

    # Mock für einen Fehler gefolgt von Erfolg
    mock_response = AsyncMock()
    mock_response.choices = [
        AsyncMock(
            message=AsyncMock(
                content='{"incident_id": "test", "severity": "low", "analysis": "test", '
                '"suggested_workflow": {"action": "test", "confidence": 0.9, "reasoning": "test"}}'
            )
        )
    ]

    mock_create = AsyncMock(side_effect=[Exception("Temp Error"), mock_response])
    with patch("app.services.ai_analyst.client.chat.completions.create", mock_create):
        result = await analyze_incident(incident)
        assert result.suggested_workflow["action"] == "test"
        assert mock_create.call_count == 2
