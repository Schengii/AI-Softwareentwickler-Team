import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, get_db, CheckHistory
from app.monitor.checker import monitor

# In-Memory SQLite für Tests. poolclass=StaticPool ist zwingend: ohne ihn bekommt jede neue
# Connection (z.B. vom TestClient in einem anderen Thread) eine eigene, leere :memory:-DB -
# die Tabellen aus Base.metadata.create_all() im Fixture waeren dann fuer App-Requests
# unsichtbar ("no such table").
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()

@pytest.fixture
def client():
    # Reset monitor
    monitor.checks = {}
    monitor.subscribers = set()
    return TestClient(app)

def test_get_check_history(client):
    # 1. Setup: Check erstellen
    check_response = client.post("/checks", json={"url": "http://example.com"})
    check_id = check_response.json()["id"]

    # 2. Setup: Historie manuell in DB einfügen
    db = TestingSessionLocal()
    history_entry = CheckHistory(check_id=check_id, latency=150.5, status_code=200)
    db.add(history_entry)
    db.commit()
    db.close()

    # 3. Test: Endpunkt abrufen
    response = client.get(f"/checks/{check_id}/history")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["check_id"] == check_id
    assert data[0]["latency"] == 150.5
    assert data[0]["status_code"] == 200
