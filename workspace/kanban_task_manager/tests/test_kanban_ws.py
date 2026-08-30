import pytest
import asyncio
from fastapi.testclient import TestClient
from app.main import app
from app.models import Task, engine
from sqlmodel import Session, select

# Test-Client für die API
client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    # Setup: Task in DB erstellen
    with Session(engine) as session:
        task = Task(title="Test Task", status="todo")
        session.add(task)
        session.commit()
        session.refresh(task)
        yield task
        # Cleanup
        session.delete(task)
        session.commit()

def test_websocket_task_moved(setup_db):
    """
    Testet den WebSocket-Workflow:
    1. Verbindung zum WebSocket
    2. Senden von 'task_moved'
    3. Empfang des Broadcasts
    4. Überprüfung der DB-Persistenz
    """
    task = setup_db
    
    with client.websocket_connect("/ws/kanban") as websocket:
        # Sende Update-Payload
        payload = {
            "type": "task_moved",
            "taskId": task.id,
            "newStatus": "in_progress"
        }
        websocket.send_json(payload)
        
        # Empfange Broadcast
        data = websocket.receive_json()
        assert data["type"] == "task_updated"
        assert data["taskId"] == task.id
        assert data["newStatus"] == "in_progress"
        
    # Überprüfe DB-State
    with Session(engine) as session:
        updated_task = session.get(Task, task.id)
        assert updated_task.status == "in_progress"

def test_websocket_invalid_payload():
    """
    Testet, wie das System auf ungültige Payloads reagiert.
    Aktuell: json.loads ohne Schema-Validierung.
    """
    with client.websocket_connect("/ws/kanban") as websocket:
        # Sende ungültigen JSON-String
        websocket.send_text("invalid json")
        # Hier sollte das System idealerweise nicht abstürzen
        # Aktuell führt json.loads zu einem Fehler, der den Loop beendet
        with pytest.raises(Exception):
            websocket.receive_json()
