import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.testclient import TestClient

from app.db.database import Base, get_async_session
from app.main import LogResponse, app

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

@pytest.fixture(scope="function")
async def test_session():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

@pytest.fixture(autouse=True)
def override_db(test_session):
    async def _get_test_session():
        yield test_session

    app.dependency_overrides[get_async_session] = _get_test_session
    yield
    app.dependency_overrides.clear()

# 1. Smoke-Test
@pytest.mark.asyncio
async def test_app_starts_and_health_ok():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

# 2. Ingestion & Persistenz Roundtrip
@pytest.mark.asyncio
async def test_create_log_success(test_session: AsyncSession):
    payload = {
        "level": "INFO",
        "service_name": "payment-service",
        "payload": "Payment processed successfully"
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/api/logs", json=payload)
    
    assert response.status_code == 200
    data = response.json()
    validated = LogResponse.model_validate(data)
    assert validated.service_name == "payment-service"
    assert validated.level == "INFO"
    assert validated.id is not None

# 3. Security & Validation Tests
@pytest.mark.asyncio
async def test_create_log_missing_fields():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/api/logs", json={"service_name": "auth-service"})
    assert response.status_code == 422

@pytest.mark.asyncio
async def test_xss_payload_stored_safely():
    xss_payload = "<script>alert('xss')</script>"
    payload = {
        "level": "WARN",
        "service_name": "gateway",
        "payload": xss_payload
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/api/logs", json=payload)
    
    assert response.status_code == 200
    data = response.json()
    # Sicherstellen, dass gefährliche Skripte unschädlich gemacht wurden und kein rohes HTML-Tag persistiert/zurückgegeben wird
    assert "<script>" not in data["payload"]
    assert "alert" in data["payload"]

# 4. WebSocket Live-Stream Test
def test_websocket_stream_and_broadcast():
    client = TestClient(app)
    with client.websocket_connect("/ws/logs") as ws:
        # Ingestion auslösen
        post_resp = client.post("/api/logs", json={
            "level": "ERROR",
            "service_name": "order-service",
            "payload": "Database connection failed"
        })
        assert post_resp.status_code == 200
        
        # Nachricht via WebSocket empfangen
        msg = ws.receive_json()
        assert msg["level"] == "ERROR"
        assert msg["service_name"] == "order-service"
        assert msg["payload"] == "Database connection failed"
