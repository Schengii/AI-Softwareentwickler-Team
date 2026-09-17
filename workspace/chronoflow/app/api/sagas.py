import asyncio
import json
import logging
from typing import List, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.orchestrator import SagaOrchestrator
from app.db.session import async_session_maker, get_db
from app.models.saga import Saga, SagaStatus, StepStatus
from app.schemas.saga import SagaCreate, SagaResponse

logger = logging.getLogger("chronoflow.api.sagas")


class ConnectionManager:
    """Verwaltet aktive WebSocket-Verbindungen für Echtzeit-Updates."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """Akzeptiert die WebSocket-Verbindung explizit."""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("WebSocket-Client verbunden. Aktive Verbindungen: %d", len(self.active_connections))

    def disconnect(self, websocket: WebSocket) -> None:
        """Entfernt einen getrennten WebSocket-Client."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info("WebSocket-Client getrennt. Aktive Verbindungen: %d", len(self.active_connections))

    async def broadcast(self, message: dict) -> None:
        """Sendet Status-Updates per Broadcast an alle verbundenen Clients."""
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:  # noqa: BLE001
                self.disconnect(connection)


manager = ConnectionManager()

router = APIRouter(prefix="/api/v1/sagas", tags=["sagas"])
ws_router = APIRouter(tags=["websockets"])


@ws_router.websocket("/ws/sagas")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Zentraler WebSocket-Endpunkt für Echtzeit-Ereignisse der Sagas."""
    await manager.connect(websocket)
    try:
        while True:
            # Verbindung offen halten und eingehende Ping/Pong-Texte empfangen
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:  # noqa: BLE001 - Robuste Bereinigung bei Verbindungsabbrüchen
        manager.disconnect(websocket)


async def run_saga_background(saga_id: int) -> None:
    """Führt die Saga asynchron im Hintergrund aus und broadcastet den Fortschritt."""
    # Kurzes Delay, um Race Conditions mit dem initialen Commit des Request-Handlers zu verhindern
    await asyncio.sleep(0.05)
    async with async_session_maker() as session:
        orchestrator = SagaOrchestrator(session, broadcast_fn=manager.broadcast)
        try:
            await orchestrator.execute_saga(saga_id)
        except Exception as exc:  # noqa: BLE001 - Hintergrund-Task darf nicht unbemerkt crashen
            logger.error("Fehler bei Ausführung der Saga %s: %s", saga_id, exc)


@router.post("", response_model=SagaResponse, status_code=status.HTTP_201_CREATED)
async def create_saga(
    saga_in: SagaCreate,
    response: Response,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> SagaResponse:
    """Erstellt eine neue Saga oder gibt bei identischem Idempotency-Key das bestehende Ergebnis zurück."""
    if idempotency_key:
        query = (
            select(Saga)
            .where(Saga.idempotency_key == idempotency_key)
            .options(selectinload(Saga.steps))
        )
        result = await db.execute(query)
        existing_saga = result.scalar_one_or_none()
        if existing_saga:
            response.status_code = status.HTTP_200_OK
            return SagaResponse.model_validate(existing_saga)

    new_saga = Saga(
        name=saga_in.name,
        payload=saga_in.payload,
        status=SagaStatus.PENDING,
        idempotency_key=idempotency_key,
    )
    db.add(new_saga)
    await db.commit()
    await db.refresh(new_saga)

    orchestrator = SagaOrchestrator(db, broadcast_fn=manager.broadcast)
    await orchestrator.create_steps_for_saga(new_saga.id, saga_in.steps)
    await db.commit()

    # Nach erfolgreichem Commit der Steps Saga mit Eager Loading neu laden
    query = (
        select(Saga)
        .where(Saga.id == new_saga.id)
        .options(selectinload(Saga.steps))
    )
    result = await db.execute(query)
    full_saga = result.scalar_one()

    # Hintergrund-Task zur Ausführung einplanen
    background_tasks.add_task(run_saga_background, new_saga.id)

    return SagaResponse.model_validate(full_saga)


@router.get("", response_model=List[SagaResponse])
async def list_sagas(db: AsyncSession = Depends(get_db)) -> List[SagaResponse]:
    """Liefert alle Sagas sortiert nach Erstelldatum."""
    query = select(Saga).options(selectinload(Saga.steps)).order_by(Saga.created_at.desc())
    result = await db.execute(query)
    sagas = result.scalars().all()
    return [SagaResponse.model_validate(s) for s in sagas]


@router.get("/{saga_id}", response_model=SagaResponse)
async def get_saga(saga_id: int, db: AsyncSession = Depends(get_db)) -> SagaResponse:
    """Liefert Details zu einer spezifischen Saga anhand der ID."""
    query = select(Saga).where(Saga.id == saga_id).options(selectinload(Saga.steps))
    result = await db.execute(query)
    saga = result.scalar_one_or_none()
    if not saga:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Saga mit ID {saga_id} nicht gefunden",
        )
    return SagaResponse.model_validate(saga)
