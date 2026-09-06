"""Umfassende Integrationstests für alle REST-Endpunkte von feature_pilot."""

from fastapi.testclient import TestClient


def test_health_check(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_auth_login_and_me(client: TestClient):
    # Login form
    login_data = {"username": "testuser@example.com", "password": "securepassword123"}
    response = client.post("/api/v1/auth/login", data=login_data)
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    token = data["access_token"]

    # Me endpoint
    headers = {"Authorization": f"Bearer {token}"}
    me_resp = client.get("/api/v1/users/me", headers=headers)
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["email"] == "testuser@example.com"
    assert me_data["is_active"] is True


def test_crud_items_lifecycle(client: TestClient):
    # 1. Leere Liste abrufen
    resp = client.get("/api/v1/items")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    # 2. Neues Item erstellen
    payload = {"title": "Dark Mode Toggle", "description": "Umschalten zwischen Hell und Dunkel"}
    create_resp = client.post("/api/v1/items", json=payload)
    assert create_resp.status_code == 201
    item_data = create_resp.json()
    item_id = item_data["id"]
    assert item_data["title"] == "Dark Mode Toggle"
    assert item_data["description"] == "Umschalten zwischen Hell und Dunkel"

    # 3. Item einzeln abrufen
    get_resp = client.get(f"/api/v1/items/{item_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == item_id

    # 4. Item aktualisieren
    update_payload = {"title": "Dark Mode v2", "description": "Mit System-Präferenz"}
    put_resp = client.put(f"/api/v1/items/{item_id}", json=update_payload)
    assert put_resp.status_code == 200
    assert put_resp.json()["title"] == "Dark Mode v2"

    # 5. Item löschen
    del_resp = client.delete(f"/api/v1/items/{item_id}")
    assert del_resp.status_code == 204

    # 6. Gelöschtes Item abrufen -> 404
    missing_resp = client.get(f"/api/v1/items/{item_id}")
    assert missing_resp.status_code == 404
