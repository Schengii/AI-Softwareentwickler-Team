import pytest

# Import der App (wird in Iteration 1 erstellt, daher hier der Import-Pfad)
# from app.main import app

@pytest.mark.asyncio
async def test_app_starts_and_health_ok():
    # Da app/main.py noch nicht existiert, ist dies ein Smoke-Test,
    # der nach der Implementierung von app/main.py funktionieren muss.
    # Für den Moment dient er als Platzhalter für die Test-Struktur.
    pytest.skip("App noch nicht implementiert")
    # transport = ASGITransport(app=app)
    # async with AsyncClient(transport=transport, base_url="http://test") as client:
    #     response = await client.get("/health")
    #     assert response.status_code == 200
