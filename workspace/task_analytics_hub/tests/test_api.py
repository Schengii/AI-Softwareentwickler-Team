import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.main import app
from app.db.session import Base, get_async_session
from app.schemas.schemas import TaskResponse, TeamMetricResponse

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

@pytest_asyncio.fixture(scope="function")
async def test_session():
    # Erstelle In-Memory-Testdatenbank
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async_session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    async with async_session_maker() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        
    await engine.dispose()

@pytest_asyncio.fixture(scope="function")
async def client(test_session: AsyncSession):
    async def override_get_async_session():
        yield test_session

    app.dependency_overrides[get_async_session] = override_get_async_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()

# --- Smoke Tests ---

@pytest.mark.asyncio
async def test_app_starts_and_health_ok(client: AsyncClient):
    """Smoke-Test: Prüft, ob die App startet und der Health-Endpoint 200 liefert."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

@pytest.mark.asyncio
async def test_static_files_root_serves_html(client: AsyncClient):
    """Smoke-Test: Prüft, ob StaticFiles unter / bereitgestellt werden."""
    response = await client.get("/")
    assert response.status_code == 200

# --- Tasks CRUD & Roundtrip Tests ---

@pytest.mark.asyncio
async def test_create_and_get_task_roundtrip(client: AsyncClient):
    """Prüft Erstellung und anschließenden Leseabruf einer Task (Roundtrip & Pydantic Typ-Validierung)."""
    payload = {
        "title": "Implement Test Suite",
        "description": "Erstelle umfassende Tests für das Backend",
        "status": "in_progress"
    }
    # 1. Erstellen (POST)
    res_post = await client.post("/api/tasks", json=payload)
    assert res_post.status_code == 201
    task_created = res_post.json()
    validated_task = TaskResponse.model_validate(task_created)
    assert validated_task.title == payload["title"]
    assert validated_task.status == "in_progress"
    task_id = validated_task.id

    # 2. Lesen (GET by ID) - Sicherstellen, dass die Daten WIRKLICH in der DB liegen
    res_get = await client.get(f"/api/tasks/{task_id}")
    assert res_get.status_code == 200
    task_read = res_get.json()
    assert TaskResponse.model_validate(task_read).id == task_id

    # 3. In Liste auffindbar (GET all)
    res_list = await client.get("/api/tasks")
    assert res_list.status_code == 200
    tasks_list = res_list.json()
    assert any(t["id"] == task_id for t in tasks_list)

@pytest.mark.asyncio
async def test_update_task(client: AsyncClient):
    """Prüft das Aktualisieren einer bestehenden Task."""
    create_res = await client.post("/api/tasks", json={"title": "Old Title", "status": "pending"})
    task_id = create_res.json()["id"]

    update_payload = {"title": "New Title", "status": "completed"}
    update_res = await client.put(f"/api/tasks/{task_id}", json=update_payload)
    assert update_res.status_code == 200
    updated_data = update_res.json()
    assert updated_data["title"] == "New Title"
    assert updated_data["status"] == "completed"

    # Verifiziere per GET
    get_res = await client.get(f"/api/tasks/{task_id}")
    assert get_res.json()["title"] == "New Title"

@pytest.mark.asyncio
async def test_delete_task(client: AsyncClient):
    """Prüft das Löschen einer Task und anschließendes 404."""
    create_res = await client.post("/api/tasks", json={"title": "To Delete"})
    task_id = create_res.json()["id"]

    delete_res = await client.delete(f"/api/tasks/{task_id}")
    assert delete_res.status_code == 204

    # GET muss 404 liefern
    get_res = await client.get(f"/api/tasks/{task_id}")
    assert get_res.status_code == 404

@pytest.mark.asyncio
async def test_get_nonexistent_task_returns_404(client: AsyncClient):
    """Prüft Fehlerbehandlung bei nicht existierender Task-ID."""
    res = await client.get("/api/tasks/99999")
    assert res.status_code == 404

@pytest.mark.asyncio
async def test_update_nonexistent_task_returns_404(client: AsyncClient):
    """Prüft Fehlerbehandlung beim Aktualisieren einer nicht existierenden Task-ID."""
    res = await client.put("/api/tasks/99999", json={"title": "Ghost"})
    assert res.status_code == 404

@pytest.mark.asyncio
async def test_delete_nonexistent_task_returns_404(client: AsyncClient):
    """Prüft Fehlerbehandlung beim Löschen einer nicht existierenden Task-ID."""
    res = await client.delete("/api/tasks/99999")
    assert res.status_code == 404

# --- Team Metrics CRUD & Roundtrip Tests ---

@pytest.mark.asyncio
async def test_create_and_get_metric_roundtrip(client: AsyncClient):
    """Prüft Erstellung und Abruf von Metriken (Roundtrip & Pydantic Typ-Validierung)."""
    payload = {
        "metric_name": "deployment_frequency",
        "value": 4.5,
        "notes": "4.5 deploys per day"
    }
    res_post = await client.post("/api/metrics", json=payload)
    assert res_post.status_code == 201
    created_metric = res_post.json()
    validated = TeamMetricResponse.model_validate(created_metric)
    assert validated.metric_name == payload["metric_name"]
    assert validated.value == 4.5
    metric_id = validated.id

    # GET by ID
    res_get = await client.get(f"/api/metrics/{metric_id}")
    assert res_get.status_code == 200
    assert TeamMetricResponse.model_validate(res_get.json()).id == metric_id

    # GET List
    res_list = await client.get("/api/metrics")
    assert res_list.status_code == 200
    assert any(m["id"] == metric_id for m in res_list.json())

@pytest.mark.asyncio
async def test_delete_metric(client: AsyncClient):
    """Prüft das Löschen von Metriken."""
    res_post = await client.post("/api/metrics", json={"metric_name": "lead_time", "value": 12.0})
    metric_id = res_post.json()["id"]

    del_res = await client.delete(f"/api/metrics/{metric_id}")
    assert del_res.status_code == 204

    get_res = await client.get(f"/api/metrics/{metric_id}")
    assert get_res.status_code == 404

@pytest.mark.asyncio
async def test_get_nonexistent_metric_returns_404(client: AsyncClient):
    """Prüft 404 für nicht gefundene Metrik-ID."""
    res = await client.get("/api/metrics/99999")
    assert res.status_code == 404

@pytest.mark.asyncio
async def test_delete_nonexistent_metric_returns_404(client: AsyncClient):
    """Prüft 404 beim Löschen nicht gefundener Metrik-ID."""
    res = await client.delete("/api/metrics/99999")
    assert res.status_code == 404

# --- Validation Tests ---

@pytest.mark.asyncio
async def test_create_task_validation_error(client: AsyncClient):
    """Prüft Validierungsfehler bei fehlendem Pflichtfeld."""
    res = await client.post("/api/tasks", json={})
    assert res.status_code == 422

@pytest.mark.asyncio
async def test_create_metric_validation_error(client: AsyncClient):
    """Prüft Validierungsfehler bei falschem Datentyp."""
    res = await client.post("/api/metrics", json={"metric_name": "lead_time", "value": "not-a-number"})
    assert res.status_code == 422
