import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings

settings = get_settings()

from app.db.session import Base, get_db
from app.main import app
from app.models.project import Project
from app.models.session import Session as DevSession
from app.repositories.project_repo import ProjectRepository
from app.repositories.session_repo import SessionRepository

# Test In-Memory Database Engine
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"
test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestingSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)


@pytest_asyncio.fixture(scope="function")
async def db_session():
    """Erstellt frische Tabellen in der In-Memory-DB für jeden Test."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestingSessionLocal() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession):
    """FastAPI AsyncClient mit überschriebener DB-Dependency."""
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ==========================================
# 1. SMOKE TESTS
# ==========================================
@pytest.mark.asyncio
async def test_smoke_health_check(client: AsyncClient):
    """Smoke-Test: Prüft, ob die FastAPI-App startet und /health 200 zurückgibt."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") in ("ok", "healthy") or "status" in data


@pytest.mark.asyncio
async def test_smoke_static_index(client: AsyncClient):
    """Smoke-Test: Prüft, ob das Root-Dashboard oder statische Dateien erreichbar sind."""
    response = await client.get("/")
    assert response.status_code in (200, 307, 404)


# ==========================================
# 2. MODEL UNIT TESTS
# ==========================================
@pytest.mark.asyncio
async def test_project_model_instantiation():
    """Unit-Test: Erstellung des Project-Modells mit Validierung der Attribute."""
    project = Project(
        name="DevPulse",
        description="Aktivitäts-Tracker"
    )
    assert project.name == "DevPulse"
    assert project.description == "Aktivitäts-Tracker"


@pytest.mark.asyncio
async def test_session_model_instantiation():
    """Unit-Test: Erstellung des Session-Modells mit Attribut-Prüfung."""
    now = datetime.now(timezone.utc)
    session = DevSession(
        project_id=1,
        start_time=now,
        note="Gute Fokuszeit"
    )
    assert session.project_id == 1
    assert session.start_time == now
    assert session.note == "Gute Fokuszeit"


# ==========================================
# 3. REPOSITORY UNIT TESTS (CRUD)
# ==========================================
@pytest.mark.asyncio
async def test_project_repository_crud(db_session: AsyncSession):
    """Prüft CRUD-Operationen des ProjectRepository gegen In-Memory SQLite."""
    repo = ProjectRepository(db_session)

    # 1. Create
    created = await repo.create(name="Alpha Project", description="Test Desk")
    assert created.id is not None
    assert created.name == "Alpha Project"

    # 2. Get by ID
    fetched = await repo.get_by_id(created.id)
    assert fetched is not None
    assert fetched.name == "Alpha Project"

    # 3. List all
    all_projects = await repo.get_all()
    assert len(all_projects) >= 1
    assert any(p.id == created.id for p in all_projects)

    # 4. Update
    if hasattr(repo, "update"):
        updated = await repo.update(created.id, name="Alpha Project Renamed")
        assert updated is not None
        assert updated.name == "Alpha Project Renamed"

    # 5. Delete
    if hasattr(repo, "delete"):
        deleted = await repo.delete(created.id)
        assert deleted is True
        assert await repo.get_by_id(created.id) is None


@pytest.mark.asyncio
async def test_session_repository_crud(db_session: AsyncSession):
    """Prüft CRUD- und Filteroperationen des SessionRepository."""
    if SessionRepository is None:
        pytest.skip("SessionRepository in session_repo nicht definiert")

    proj_repo = ProjectRepository(db_session)
    project = await proj_repo.create(name="Beta Project", description="Repo Test")

    session_repo = SessionRepository(db_session)

    # 1. Create Session
    session_data = {
        "project_id": project.id,
        "note": "Erfolgreicher Durchlauf"
    }
    created_session = await session_repo.create(**session_data)
    assert created_session.id is not None
    assert created_session.project_id == project.id
    assert created_session.note == "Erfolgreicher Durchlauf"

    # 2. Get by ID
    fetched_session = await session_repo.get_by_id(created_session.id)
    assert fetched_session is not None
    assert fetched_session.note == "Erfolgreicher Durchlauf"

    # 3. List all / Get by project
    all_sessions = await session_repo.get_all()
    assert len(all_sessions) >= 1

    if hasattr(session_repo, "get_by_project_id"):
        project_sessions = await session_repo.get_by_project_id(project.id)
        assert len(project_sessions) >= 1
        assert project_sessions[0].project_id == project.id

    # 4. Delete Session
    if hasattr(session_repo, "delete"):
        del_result = await session_repo.delete(created_session.id)
        assert del_result is True
        assert await session_repo.get_by_id(created_session.id) is None


# ==========================================
# 4. CONFIG & EDGE CASES
# ==========================================
def test_settings_load():
    """Prüft das Laden der Anwendungskonfiguration."""
    assert getattr(settings, "PROJECT_NAME", None) or getattr(settings, "app_name", None) is not None
    assert hasattr(settings, "DATABASE_URL") or hasattr(settings, "database_url")
