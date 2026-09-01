import pytest
from fastapi.testclient import TestClient
from main import app, get_db
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from models import Base

# Setup für In-Memory SQLite für Tests
DATABASE_URL = "sqlite+aiosqlite:///:memory:"
engine = create_async_engine(DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _override_get_db():
    async with TestingSessionLocal() as session:
        yield session


# Ohne diesen Override greift die App weiterhin auf models.AsyncSessionLocal zu, das auf
# eine ANDERE Datenbank zeigt (produktiv: sqlite-Datei ./polls.db) als das In-Memory-Test-
# Engine oben, gegen das setup_db() die Tabellen anlegt - die Tabellen aus setup_db()
# existieren dann für die App-Requests schlicht nicht ("no such table").
app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

client = TestClient(app)

def test_create_poll():
    # PollCreate.options ist eine Liste von OptionCreate-Objekten ({"text": ...}), keine
    # Liste roher Strings (siehe schemas.py).
    response = client.post(
        "/polls",
        json={"title": "Test Poll", "options": [{"text": "A"}, {"text": "B"}]},
    )
    assert response.status_code == 200
    assert "id" in response.json()

def test_websocket_connection():
    # Testet, ob der WebSocket-Endpunkt grundsätzlich erreichbar ist (Endpoint verlangt
    # einen "token"-Header zur Authentifizierung, siehe main.py).
    with client.websocket_connect(
        "/ws/polls/1", headers={"token": "secret-token"}
    ) as websocket:
        assert websocket is not None
