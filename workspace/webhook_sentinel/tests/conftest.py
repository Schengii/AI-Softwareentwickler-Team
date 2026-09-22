import pytest
from httpx import ASGITransport, AsyncClient

try:
    from app.main import app
except ImportError:
    try:
        from main import app
    except ImportError:
        app = None


@pytest.fixture
async def async_client():
    """Standardisierter AsyncClient mit ASGITransport für FastAPI-Tests."""
    if app is None:
        pytest.skip("FastAPI-App noch nicht importierbar")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
