import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from app.main import app, get_db
from app.database import Base

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()
        Base.metadata.drop_all(bind=engine)

@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        yield db_session
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()

def test_create_snippet(client):
    response = client.post("/snippets", json={"title": "Test", "content": "print('hi')", "language": "python", "tags": ["test"]})
    assert response.status_code == 200
    assert response.json()["title"] == "Test"

def test_read_snippets(client):
    response = client.get("/snippets")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_get_tags(client):
    response = client.get("/tags")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
