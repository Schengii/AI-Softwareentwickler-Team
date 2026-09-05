import pytest
from httpx import ASGITransport, AsyncClient
from main import app
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from models import Base

# Test-Datenbank Konfiguration
DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(DATABASE_URL, echo=False)
TestingSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

@pytest.fixture(scope="session")
async def db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest.fixture
async def client(db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

@pytest.mark.asyncio
async def test_smoke_app(client):
    """Testet, ob die App läuft."""
    response = await client.get("/tasks/")
    assert response.status_code == 200

@pytest.mark.asyncio
async def test_create_task(client):
    """Testet das Erstellen eines Tasks."""
    response = await client.post("/tasks/", json={"title": "Test Task", "description": "Test Desc"})
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Test Task"
    assert "id" in data

@pytest.mark.asyncio
async def test_read_tasks(client):
    """Testet das Abrufen der Tasks."""
    response = await client.get("/tasks/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
