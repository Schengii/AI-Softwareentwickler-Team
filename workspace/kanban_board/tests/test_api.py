import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool
from main import app
from database import get_session
from models import Board, Column, Card

# In-Memory DB für Tests
sqlite_url = "sqlite:///:memory:"
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)

def get_test_session():
    with Session(engine) as session:
        yield session

app.dependency_overrides[get_session] = get_test_session

@pytest.fixture(name="session")
def session_fixture():
    SQLModel.metadata.create_all(engine)
    yield Session(engine)
    SQLModel.metadata.drop_all(engine)

@pytest.fixture(name="client")
def client_fixture(session: Session):
    return TestClient(app)

def test_create_board(client):
    response = client.post("/boards/", json={"title": "Test Board"})
    assert response.status_code == 200
    assert response.json()["title"] == "Test Board"

def test_move_card_not_found(client):
    response = client.patch("/cards/999/move?new_column_id=1&new_position=1")
    assert response.status_code == 404
