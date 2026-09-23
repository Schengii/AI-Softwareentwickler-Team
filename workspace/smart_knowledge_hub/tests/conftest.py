import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

try:
    from app.main import app
except ImportError:
    try:
        from main import app
    except ImportError:
        app = None


async def poll_until(async_fn, *, max_attempts: int = 20, delay: float = 0.05):
    """Wartet bis async_fn() einen truthy Wert zurückgibt (oder max_attempts erschöpft sind).

    Realer Fund (omnimetric_engine, 2026-09-22, root-cause-omnimetric_engine-asynchrone-race-
    condition-im-alert-test): Background-Tasks laufen nach dem auslösenden POST noch kurz
    weiter. Tests, die direkt danach den Zustand abfragen (GET /alerts), sehen noch den alten
    Zustand und schlagen scheinbar zufällig fehl. `poll_until` verhindert diese Race-Condition:

        result = await poll_until(lambda: client.get("/api/v1/alerts"))
        # oder mit Bedingung:
        async def check():
            r = await client.get("/api/v1/jobs/1")
            return r if r.json().get("status") == "done" else None
        result = await poll_until(check)
    """
    for _ in range(max_attempts):
        result = await async_fn() if asyncio.iscoroutinefunction(async_fn) else async_fn()
        if result:
            return result
        await asyncio.sleep(delay)
    return None


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
