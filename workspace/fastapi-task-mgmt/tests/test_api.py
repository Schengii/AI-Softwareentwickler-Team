import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from main import app
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from models import Base, get_db

# Test-Datenbank Konfiguration
DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(DATABASE_URL, echo=False)
TestingSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _override_get_db():
    async with TestingSessionLocal() as session:
        yield session


# Ohne das nutzen die über den Testclient aufgerufenen Endpunkte weiterhin models.get_db()
# (die ECHTE App-Engine, sqlite+aiosqlite:///./tasks.db) statt der oben angelegten
# In-Memory-Test-Engine - die `db`-Fixture unten würde dann Tabellen in einer völlig anderen
# Datenbank anlegen, als die Endpunkte tatsächlich verwenden ("no such table: tasks").
app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture(scope="session")
async def db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest.fixture
async def client(db):
    # Jeder Test bekommt einen frisch registrierten, eindeutigen Nutzer (statt eines geteilten
    # "tester"-Accounts über alle Tests hinweg) - `db` ist session-scoped (Tabellen bleiben über
    # alle Tests hinweg bestehen), ein fester Nutzername würde ab dem zweiten Test mit "409/400
    # Benutzername bereits vergeben" an /register scheitern. Nebeneffekt: /tasks/ ist jetzt auf
    # den angemeldeten Nutzer skoped, jeder Test sieht dadurch automatisch nur seine eigenen Tasks.
    username = f"tester_{uuid.uuid4().hex[:8]}"
    password = "testpass123"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        register_response = await ac.post("/register", json={"username": username, "password": password})
        assert register_response.status_code == 201, register_response.text
        token_response = await ac.post("/token", data={"username": username, "password": password})
        assert token_response.status_code == 200, token_response.text
        token = token_response.json()["access_token"]
        ac.headers.update({"Authorization": f"Bearer {token}"})
        yield ac

@pytest.fixture
async def anon_client(db):
    """Client OHNE Authorization-Header - für Tests, die genau das fehlende/ungültige
    Token-Verhalten prüfen sollen (die `client`-Fixture oben ist bereits angemeldet)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_register_creates_user(anon_client):
    response = await anon_client.post(
        "/register", json={"username": f"newuser_{uuid.uuid4().hex[:8]}", "password": "testpass123"},
    )
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert "password" not in data and "hashed_password" not in data


@pytest.mark.asyncio
async def test_register_duplicate_username_rejected(anon_client):
    username = f"dupe_{uuid.uuid4().hex[:8]}"
    first = await anon_client.post("/register", json={"username": username, "password": "testpass123"})
    assert first.status_code == 201
    second = await anon_client.post("/register", json={"username": username, "password": "anotherpass"})
    assert second.status_code == 400


@pytest.mark.asyncio
async def test_login_with_correct_password_returns_token(anon_client):
    username = f"login_{uuid.uuid4().hex[:8]}"
    password = "testpass123"
    await anon_client.post("/register", json={"username": username, "password": password})

    response = await anon_client.post("/token", data={"username": username, "password": password})

    assert response.status_code == 200
    data = response.json()
    assert data["token_type"] == "bearer"
    assert len(data["access_token"]) > 0


@pytest.mark.asyncio
async def test_login_with_wrong_password_rejected(anon_client):
    username = f"wrongpw_{uuid.uuid4().hex[:8]}"
    await anon_client.post("/register", json={"username": username, "password": "testpass123"})

    response = await anon_client.post("/token", data={"username": username, "password": "falsches-passwort"})

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_tasks_endpoint_requires_authentication(anon_client):
    response = await anon_client.get("/tasks/")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_tasks_are_scoped_to_authenticated_user(client, anon_client):
    # `client` (eigener, per Fixture angemeldeter Nutzer) legt einen Task an ...
    await client.post("/tasks/", json={"title": "Nur für mich"})

    # ... ein ZWEITER, unabhängig angemeldeter Nutzer darf ihn nicht sehen.
    username = f"other_{uuid.uuid4().hex[:8]}"
    password = "testpass123"
    await anon_client.post("/register", json={"username": username, "password": password})
    token = (await anon_client.post("/token", data={"username": username, "password": password})).json()["access_token"]
    anon_client.headers.update({"Authorization": f"Bearer {token}"})

    response = await anon_client.get("/tasks/")
    assert response.status_code == 200
    assert all(task["title"] != "Nur für mich" for task in response.json())


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
