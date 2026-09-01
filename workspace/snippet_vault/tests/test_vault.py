import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.main import app, get_db

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


def test_created_tags_are_persisted_and_reused(client):
    """
    Realer Fund: SnippetCreate.tags wurde beim Anlegen bisher vollständig ignoriert - jeder
    übermittelte Tag verschwand stillschweigend, /tags blieb dauerhaft leer und die
    Tag-Filterung (?tag=...) konnte nie etwas finden.
    """
    client.post("/snippets", json={"title": "A", "content": "a", "language": "python", "tags": ["fastapi", "python"]})
    client.post("/snippets", json={"title": "B", "content": "b", "language": "python", "tags": ["fastapi"]})

    tags_response = client.get("/tags")
    tag_names = {t["name"] for t in tags_response.json()}
    assert tag_names == {"fastapi", "python"}
    # "fastapi" wurde für beide Snippets übermittelt - darf trotzdem nur EINMAL angelegt
    # werden (Wiederverwendung per Name), nicht als Duplikat.
    assert len(tags_response.json()) == 2

    filtered = client.get("/snippets", params={"tag": "python"})
    assert [s["title"] for s in filtered.json()] == ["A"]
