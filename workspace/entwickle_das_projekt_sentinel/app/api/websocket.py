import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

# LOG015: Modul-Level Logger verwenden
logger = logging.getLogger(__name__)

router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        text = json.dumps(message)
        dead_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_text(text)
            except (WebSocketDisconnect, ConnectionError, RuntimeError):
                dead_connections.append(connection)
            except asyncio.CancelledError:
                dead_connections.append(connection)
                raise
        
        for dead in dead_connections:
            self.disconnect(dead)

manager = ConnectionManager()

@router.websocket("/ws/live-metrics")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, RuntimeError):
        manager.disconnect(websocket)
    except asyncio.CancelledError:
        manager.disconnect(websocket)
        raise
