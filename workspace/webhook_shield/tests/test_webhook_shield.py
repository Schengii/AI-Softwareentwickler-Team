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
async def test_webhook_shield_invalid_json(client):
    """Testet, ob der Endpunkt bei ungültigem JSON mit 422 (FastAPI default) oder 400 antwortet."""
    # Setup: Create a webhook endpoint in DB
    db = TestingSessionLocal()
    webhook = Webhook(endpoint_path="test-endpoint", hmac_secret="test-secret")
    db.add(webhook)
    db.commit()
    db.close()

    # Sende ungültigen Body (kein JSON)
    response = await client.post(
        "/webhooks/test-endpoint", 
        content="invalid-json",
        headers={"Content-Type": "application/json"}
    )
    
    # Erwartung: 422 Unprocessable Entity (FastAPI Standard für Body-Parsing Fehler)
    assert response.status_code == 422

@pytest.mark.asyncio
async def test_webhook_shield_missing_webhook(client):
    """Testet, ob ein nicht existierender Webhook-Pfad korrekt abgelehnt wird."""
    response = await client.post("/webhooks/non-existent", json={"data": "test"})
    assert response.status_code == 404
