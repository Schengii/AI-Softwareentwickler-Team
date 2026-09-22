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


@pytest.fixture
async def client(async_client):
    """Alias für `async_client` - manche Testdateien erwarten den Namen `client` statt
    `async_client`. Realer Fund (pulse_queue, 2026-09-22): der Tester benannte beim Nachrüsten
    einer weiteren Fixture `async_client` versehentlich in `client` um, wodurch ALLE Tests mit
    `fixture 'async_client' not found` scheiterten. Mit diesem Alias funktioniert BEIDE Namen von
    Anfang an - eine künftige Umbenennung in eine Richtung bricht die andere nicht mehr."""
    return async_client


@pytest.fixture
def auth_headers():
    """Platz für authentifizierte Requests (z. B. `{"X-API-Key": "..."}`). Passe WERT/Header-
    Namen an die tatsächliche Auth-Implementierung des Projekts an, aber benenne diese Fixture
    NICHT um - Testdateien erwarten exakt `auth_headers`. Ergänze bei Bedarf weitere Fixtures in
    dieser Datei, statt bestehende zu entfernen oder umzubenennen."""
    return {}
