"""Pytest Test-Setup & Fixtures für FastAPI Task-Management API.

- Konfiguriert In-Memory SQLite-Datenbank via aiosqlite.
- Überschreibt get_db Dependency für Tests.
- Stellt httpx.AsyncClient für REST-Tests bereit.
"""

import pytest
import pytest_asyncio
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from starlette.testclient import TestClient

from app.main import app, manager
from app.db.database import Base, get_db

# In-Memory SQLite für schnelle & isolierte Integrationstests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestingSessionLocal = sessionmaker(
    bind=test_engine, 
    class_=AsyncSession, 
    expire_on_commit=False
)

@pytest_asyncio.fixture(autouse=True)
async def prepare_database():
    """Erstellt Tabellen vor jedem Test und löscht sie danach."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency Override für die Test-Datenbank-Session."""
    async with TestingSessionLocal() as session:
        yield session

# Dependency der App überschreiben
app.dependency_overrides[get_db] = override_get_db

@pytest_asyncio.fixture
async def async_client():
    """httpx AsyncClient Fixture für REST-API Tests."""
    from httpx import AsyncClient
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

@pytest.fixture
def ws_client():
    """Starlette TestClient Fixture für WebSocket Tests."""
    manager.active_connections.clear()
    with TestClient(app) as client:
        yield client
