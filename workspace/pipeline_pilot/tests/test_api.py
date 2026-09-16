import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db_session, init_db
from main import app

# In-Memory SQLite für Tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
async def db_engine():
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    await init_db() # Stellt sicher, dass Tabellen existieren
    yield engine
    await engine.dispose()

@pytest.fixture(scope="function")
async def db_session(db_engine):
    async_session = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        # Tabellen explizit erstellen für jede Test-Session
        async with db_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield session
        # Tabellen wieder löschen
        async with db_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await session.rollback()

@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        yield db_session
    
    app.dependency_overrides[get_db_session] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_pipeline_crud_lifecycle(client):
    # 1. Erstellen
    payload = {
        "name": "Test Pipeline",
        "description": "Test Description",
        "trigger_type": "MANUAL",
        "steps": [{"name": "Step 1", "type": "shell", "command": "echo hello"}]
    }
    response = client.post("/api/pipelines", json=payload)
    assert response.status_code == 201
    pipeline = response.json()
    assert pipeline["name"] == "Test Pipeline"
    pipeline_id = pipeline["id"]

    # 2. Lesen
    response = client.get(f"/api/pipelines/{pipeline_id}")
    assert response.status_code == 200
    assert response.json()["id"] == pipeline_id

    # 3. Löschen
    response = client.delete(f"/api/pipelines/{pipeline_id}")
    assert response.status_code == 200
    
    # 4. Verifizieren
    response = client.get(f"/api/pipelines/{pipeline_id}")
    assert response.status_code == 404
