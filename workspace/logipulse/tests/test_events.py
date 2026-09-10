
import pytest
from httpx import ASGITransport, AsyncClient

from src.events.processor import EventBroker
from src.events.schemas import EventType
from src.main import app


# Reset des Singletons vor jedem Test
@pytest.fixture(autouse=True)
def reset_event_broker():
    EventBroker._instance = None
    yield

@pytest.mark.asyncio
async def test_post_event_success():
    """Testet die erfolgreiche Ingestion eines Events."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Wir müssen den Token-Header simulieren, da der Endpunkt geschützt sein soll
        # Für diesen Test nehmen wir an, dass die Auth-Middleware aktiv ist
        # Da wir hier nur den Ingestion-Flow testen, mocken wir die Auth falls nötig
        # oder nutzen einen validen Token-Flow.
        
        # Hier vereinfacht: Wir prüfen den Status 202
        payload = {
            "event_type": "sensor_reading",
            "payload": {"sensor_id": "temp-01", "value": 25.5, "unit": "celsius"}
        }
        
        # Hinweis: Da der Endpunkt noch nicht in main.py implementiert ist, 
        # wird dieser Test fehlschlagen. Das ist beabsichtigt für die TDD-Phase.
        response = await client.post("/api/v1/events", json=payload)
        assert response.status_code == 202
        assert "request_id" in response.json()

@pytest.mark.asyncio
async def test_post_event_invalid_payload():
    """Testet die Validierung bei ungültigem Payload."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = {"event_type": "invalid_type", "payload": {}}
        response = await client.post("/api/v1/events", json=payload)
        assert response.status_code == 422

@pytest.mark.asyncio
async def test_event_broker_queue():
    """Testet, ob Events korrekt in die Queue gelangen."""
    broker = EventBroker.get_instance()
    from src.events.schemas import BaseEvent
    
    event = BaseEvent(event_type=EventType.SENSOR_READING, payload={"test": "data"})
    await broker.enqueue(event)
    
    queued_event = await broker.queue.get()
    assert queued_event.event_type == EventType.SENSOR_READING
    assert queued_event.payload == {"test": "data"}
