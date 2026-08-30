from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status
from typing import List
from app.models import init_db, engine, Task
from app.schemas import TaskMovedPayload
from sqlmodel import Session
from pydantic import ValidationError

app = FastAPI()

# Einfacher Connection-Manager für WebSockets
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            await connection.send_json(message)

manager = ConnectionManager()

@app.on_event("startup")
def on_startup():
    init_db()

@app.websocket("/ws/kanban")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # Erwarte: {"type": "task_moved", "taskId": 1, "newStatus": "done"}
            if message.get("type") == "task_moved":
                task_id = message.get("taskId")
                new_status = message.get("newStatus")
                
                # Persistenz in PostgreSQL
                with Session(engine) as session:
                    task = session.get(Task, task_id)
                    if task:
                        task.status = new_status
                        session.add(task)
                        session.commit()
                        session.refresh(task)
                
                # Broadcast an alle Clients
                await manager.broadcast({
                    "type": "task_updated",
                    "taskId": task_id,
                    "newStatus": new_status
                })
    except WebSocketDisconnect:
        manager.disconnect(websocket)
