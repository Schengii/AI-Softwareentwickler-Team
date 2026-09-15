from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Base, engine, get_db
from app.dispatcher import dispatcher
from app.models import Endpoint, Event


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Datenbanktabellen asynchron anlegen
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Shutdown: HTTP-Client des Dispatchers sauber schließen
    await dispatcher.close()


app = FastAPI(
    title="Webhook Gateway API",
    description="Zentraler Einstiegspunkt für das Webhook-Gateway",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health", tags=["System"])
async def health_check():
    """Health-Check-Endpunkt für Monitoring und Kubernetes."""
    return {"status": "ok"}


# --- Pydantic Schemas ---

class EndpointCreate(BaseModel):
    url: str
    secret: str | None = None
    description: str | None = None


class EndpointOut(BaseModel):
    id: str
    url: str
    secret: str | None = None
    description: str | None = None

    model_config = {"from_attributes": True}


class EventCreate(BaseModel):
    payload: dict[str, Any]


class EventOut(BaseModel):
    id: str
    payload: dict[str, Any]

    model_config = {"from_attributes": True}


# --- API Endpunkte ---

@app.post("/endpoints", response_model=EndpointOut, tags=["Endpoints"])
async def create_endpoint(endpoint: EndpointCreate, db: AsyncSession = Depends(get_db)):
    """Registriert einen neuen Webhook-Endpunkt."""
    db_endpoint = Endpoint(**endpoint.model_dump())
    db.add(db_endpoint)
    await db.commit()
    await db.refresh(db_endpoint)
    return db_endpoint


@app.get("/endpoints", response_model=list[EndpointOut], tags=["Endpoints"])
async def list_endpoints(db: AsyncSession = Depends(get_db)):
    """Listet alle registrierten Webhook-Endpunkte auf."""
    result = await db.execute(select(Endpoint))
    return result.scalars().all()


@app.post("/events", response_model=EventOut, tags=["Events"])
async def create_event(
    event: EventCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Nimmt ein neues Event entgegen, speichert es und triggert die asynchrone
    Auslieferung an alle registrierten Endpunkte via BackgroundTasks.
    """
    db_event = Event(payload=event.payload)
    db.add(db_event)
    await db.commit()
    await db.refresh(db_event)
    
    # Auslieferung asynchron im Hintergrund starten
    background_tasks.add_task(dispatcher.dispatch_event, db_event.id)
    
    return db_event
