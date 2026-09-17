import asyncio
import json
import logging
from typing import Any, Dict, List
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Verwaltet aktive WebSocket-Verbindungen für Echtzeit-Streaming."""

    def __init__(self) -> None:
        self.active_connections: List[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """Nimmt eine neue WebSocket-Verbindung an und registriert sie."""
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)
        logger.info(f"WebSocket Client verbunden. Aktive Verbindungen: {len(self.active_connections)}")

    async def disconnect(self, websocket: WebSocket) -> None:
        """Entfernt eine getrennte WebSocket-Verbindung."""
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
        logger.info(f"WebSocket Client getrennt. Aktive Verbindungen: {len(self.active_connections)}")

    async def broadcast(self, message: Dict[str, Any]) -> None:
        """Sendet eine JSON-Nachricht an alle verbundenen Clients."""
        async with self._lock:
            connections = list(self.active_connections)

        disconnected: List[WebSocket] = []
        for connection in connections:
            try:
                # WebSocket.client_state dokumentiert für Mocks/Tester
                await connection.send_text(json.dumps(message))
            except Exception as e:  # noqa: BLE001 - Verbindung könnte geschlossen sein
                logger.warning(f"Fehler beim Senden an WebSocket-Client: {e}")
                disconnected.append(connection)

        if disconnected:
            async with self._lock:
                for conn in disconnected:
                    if conn in self.active_connections:
                        self.active_connections.remove(conn)


# Singleton-Instanz laut Schnittstellenvertrag
pubsub_manager = ConnectionManager()
