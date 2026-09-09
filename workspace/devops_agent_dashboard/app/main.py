from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.schemas.websocket import WSMessageWrapper
from app.services.websocket import manager

app = FastAPI(title="Agent System API")

@app.websocket(f"{settings.API_V1_STR}/ws/status")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            # Validierung via WSMessageWrapper
            validated_msg = WSMessageWrapper.model_validate(data)
            # Logik zur Verarbeitung/Broadcast
            await manager.broadcast(validated_msg.model_dump())
    except WebSocketDisconnect:
        manager.disconnect(websocket)
