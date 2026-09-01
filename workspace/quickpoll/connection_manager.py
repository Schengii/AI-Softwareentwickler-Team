import asyncio
from fastapi import WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState
from typing import Dict, List
from schemas import WSMessage

class ConnectionManager:
    def __init__(self):
        # poll_id -> list of active websockets
        self.active_connections: Dict[int, List[WebSocket]] = {}
        self.lock = asyncio.Lock()

    async def connect(self, poll_id: int, websocket: WebSocket):
        await websocket.accept()
        async with self.lock:
            if poll_id not in self.active_connections:
                self.active_connections[poll_id] = []
            self.active_connections[poll_id].append(websocket)

    async def disconnect(self, poll_id: int, websocket: WebSocket):
        async with self.lock:
            if poll_id in self.active_connections and websocket in self.active_connections[poll_id]:
                self.active_connections[poll_id].remove(websocket)
                if not self.active_connections[poll_id]:
                    del self.active_connections[poll_id]

    async def broadcast(self, poll_id: int, message: WSMessage):
        async with self.lock:
            connections = self.active_connections.get(poll_id, []).copy()
        
        for connection in connections:
            try:
                if connection.client_state == WebSocketState.CONNECTED:
                    await connection.send_json(message.model_dump())
            except (WebSocketDisconnect, RuntimeError):
                await self.disconnect(poll_id, connection)

manager = ConnectionManager()
