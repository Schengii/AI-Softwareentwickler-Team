import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app, get_db
from app.models import Base, Webhook

# In-Memory SQLite für Tests
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

@pytest.fixture(scope="function", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

@pytest.mark.asyncio
async def test_receive_webhook_404(client):
    response = await client.post("/webhooks/non-existent")
    assert response.status_code == 404

@pytest.mark.asyncio
async def test_receive_webhook_success(client):
    # Setup: Create a webhook endpoint in DB
    db = TestingSessionLocal()
    webhook = Webhook(endpoint_path="test-endpoint")
    db.add(webhook)
    db.commit()
    db.close()

    payload = {"event": "test", "data": 123}
    response = await client.post("/webhooks/test-endpoint", json=payload)
    
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"

    # Verify Roundtrip
    logs = await client.get("/logs")
    assert len(logs.json()) == 1
    assert logs.json()[0]["payload_json"] == payload
