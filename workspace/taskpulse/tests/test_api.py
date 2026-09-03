import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.main import app, get_db

# Test-Datenbank Konfiguration
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)

@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()

def test_create_and_read_task(client):
    # Test POST /tasks
    response = client.post("/tasks", json={"name": "Test Task"})
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Task"
    assert "id" in data

    # Test GET /tasks (Roundtrip)
    response = client.get("/tasks")
    assert response.status_code == 200
    tasks = response.json()
    assert len(tasks) == 1
    assert tasks[0]["name"] == "Test Task"

def test_trigger_status_check(client):
    # Test POST /status/check
    response = client.post("/status/check?url=http://example.com")
    assert response.status_code == 200
    assert response.json() == {"message": "Check initiated"}
