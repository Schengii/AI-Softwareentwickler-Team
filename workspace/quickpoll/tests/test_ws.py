import pytest
from fastapi.websockets import WebSocketState
from connection_manager import manager
from schemas import PollUpdateEvent

# asyncio_mode = auto (pytest.ini) macht @pytest.mark.asyncio ueberfluessig.


async def test_websocket_broadcast():
    # Mocking WebSocket - bildet exakt die Attribute/Methoden nach, die
    # ConnectionManager.broadcast() tatsaechlich am WebSocket-Objekt anspricht
    # (siehe connection_manager.py: .client_state und .send_json()).
    class MockWebSocket:
        def __init__(self):
            self.sent = []
            self.client_state = WebSocketState.CONNECTED

        async def send_json(self, data):
            self.sent.append(data)

        async def accept(self):
            pass

    ws = MockWebSocket()
    poll_id = 1

    await manager.connect(poll_id, ws)
    # broadcast() erwartet ein echtes WSMessage-Modell (ruft .model_dump() darauf auf),
    # kein rohes dict.
    await manager.broadcast(poll_id, PollUpdateEvent(message="update", total_votes=1))

    assert len(ws.sent) == 1
    assert ws.sent[0]["type"] == "poll_update"

    await manager.disconnect(poll_id, ws)
    assert poll_id not in manager.active_connections
