import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app  # Angenommen, die FastAPI App ist hier

client = TestClient(app)

def test_websocket_connection_unauthorized():
    # Test ohne Token: der Server lehnt den Handshake ab und schliesst die Verbindung
    # sofort wieder - das ist das erwartete Verhalten, kein Testfehler.
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/chat"):
            pass

# Integration Test für Redis Pub/Sub Flow
@pytest.mark.asyncio
async def test_redis_pubsub_flow():
    # 1. Publizieren einer Nachricht in Redis
    # 2. Prüfen, ob der WebSocket-Client sie empfängt
    pass
