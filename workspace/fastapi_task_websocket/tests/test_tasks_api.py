"""Asynchrone Tests für REST-CRUD Route-Operationen (`/tasks`)."""

import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_list_tasks_empty(async_client: AsyncClient):
    """Prüft, ob GET /tasks bei leerer DB eine leere Liste zurückgibt."""
    response = await async_client.get("/tasks")
    assert response.status_code == 200
    assert response.json() == []

@pytest.mark.asyncio
async def test_create_task_success(async_client: AsyncClient):
    """Prüft das erfolgreiche Erstellen eines Tasks via POST /tasks."""
    payload = {
        "title": "Dokumentation schreiben",
        "description": "REST & WS API testen",
        "status": "Todo",
        "assignee": "QA Specialist"
    }
    response = await async_client.post("/tasks", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == payload["title"]
    assert data["description"] == payload["description"]
    assert data["status"] == "Todo"
    assert data["assignee"] == payload["assignee"]
    assert "id" in data
    assert "created_at" in data

@pytest.mark.asyncio
async def test_create_task_validation_error(async_client: AsyncClient):
    """Prüft, ob POST /tasks ohne Pflichtfeld title mit HTTP 422 fehlschlägt."""
    payload = {
        "description": "Task ohne Titel"
    }
    response = await async_client.post("/tasks", json=payload)
    assert response.status_code == 422

@pytest.mark.asyncio
async def test_get_task_by_id_success(async_client: AsyncClient):
    """Prüft das Abrufen eines spezifischen Tasks via GET /tasks/{id}."""
    create_resp = await async_client.post("/tasks", json={"title": "Test Task"})
    task_id = create_resp.json()["id"]

    response = await async_client.get(f"/tasks/{task_id}")
    assert response.status_code == 200
    assert response.json()["id"] == task_id
    assert response.json()["title"] == "Test Task"

@pytest.mark.asyncio
async def test_get_task_not_found(async_client: AsyncClient):
    """Prüft, dass GET /tasks/{id} bei ungültiger ID HTTP 404 zurückgibt."""
    response = await async_client.get("/tasks/9999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Task not found"

@pytest.mark.asyncio
async def test_update_task_status_transition(async_client: AsyncClient):
    """Prüft die Aktualisierung von Status und Eigenschaften via PUT /tasks/{id}."""
    create_resp = await async_client.post("/tasks", json={"title": "Refactoring", "status": "Todo"})
    task_id = create_resp.json()["id"]

    # Statuswechsel zu In Progress
    update_payload = {"status": "In Progress", "assignee": "Dev Team"}
    update_resp = await async_client.put(f"/tasks/{task_id}", json=update_payload)
    assert update_resp.status_code == 200
    assert update_resp.json()["status"] == "In Progress"
    assert update_resp.json()["assignee"] == "Dev Team"

    # Statuswechsel zu Done
    update_resp_done = await async_client.put(f"/tasks/{task_id}", json={"status": "Done"})
    assert update_resp_done.status_code == 200
    assert update_resp_done.json()["status"] == "Done"

@pytest.mark.asyncio
async def test_update_task_not_found(async_client: AsyncClient):
    """Prüft, dass PUT /tasks/{id} bei ungültiger ID HTTP 404 zurückgibt."""
    response = await async_client.put("/tasks/9999", json={"title": "Neuer Titel"})
    assert response.status_code == 404

@pytest.mark.asyncio
async def test_delete_task_success(async_client: AsyncClient):
    """Prüft das Löschen eines Tasks via DELETE /tasks/{id} und Verifizierung."""
    create_resp = await async_client.post("/tasks", json={"title": "Zu löschende Task"})
    task_id = create_resp.json()["id"]

    # Delete Aufruf
    delete_resp = await async_client.delete(f"/tasks/{task_id}")
    assert delete_resp.status_code == 200
    assert delete_resp.json()["detail"] == "Task deleted"

    # Nachprüfen via GET
    get_resp = await async_client.get(f"/tasks/{task_id}")
    assert get_resp.status_code == 404
