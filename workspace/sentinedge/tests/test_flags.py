import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_feature_flag_rollout_logic():
    # Wir testen hier die Logik des Flag-Services (via API)
    # Annahme: POST /flags/ {name, percentage}
    # GET /flags/{name}/check?user_id=...
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Flag erstellen (50% Rollout)
        resp = await ac.post("/flags/", json={"name": "test-flag", "percentage": 50})
        assert resp.status_code == 201
        
        # 2. Check für verschiedene User
        # Da der Algorithmus deterministisch sein sollte (Hash(user_id + flag_name)),
        # prüfen wir, ob die Verteilung stabil ist.
        results = []
        for i in range(100):
            resp = await ac.get(f"/flags/test-flag/check?user_id=user_{i}")
            assert resp.status_code == 200
            results.append(resp.json()["enabled"])
            
        # Bei 50% sollten ca. 50 enabled sein
        enabled_count = sum(results)
        assert 30 <= enabled_count <= 70  # Toleranz für statistische Varianz
