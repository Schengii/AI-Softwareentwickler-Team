"""Zentrale Pytest-Fixtures für ChronosPulse."""
from __future__ import annotations

from typing import AsyncGenerator
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app, event_hub
from app.ml.anomaly_detector import anomaly_detector


@pytest_asyncio.fixture(scope="function")
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Asynchroner Test-Client mit sauberem State-Reset vor jedem Testlauf."""
    # State-Reset des EventHubs und des AnomalyDetectors
    event_hub.metrics_history.clear()
    event_hub.anomalies_history.clear()
    event_hub.webhooks_history.clear()
    event_hub.metric_subscribers.clear()
    anomaly_detector.baselines.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    # Teardown
    event_hub.metrics_history.clear()
    event_hub.anomalies_history.clear()
    event_hub.webhooks_history.clear()
