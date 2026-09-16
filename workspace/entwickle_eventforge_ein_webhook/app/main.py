import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    select,
)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship

logger = logging.getLogger("eventforge")
logging.basicConfig(level=logging.INFO)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./eventforge.db")

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Bucket(Base):
    __tablename__ = "buckets"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False)
    forward_url = Column(String(500), nullable=True)
    expires_in_hours = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    events = relationship("Event", back_populates="bucket", cascade="all, delete-orphan")


class Event(Base):
    __tablename__ = "events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    bucket_id = Column(String(36), ForeignKey("buckets.id", ondelete="CASCADE"), nullable=False)
    method = Column(String(10), nullable=False)
    headers = Column(Text, nullable=False)  # JSON-encoded
    payload = Column(Text, nullable=True)
    client_ip = Column(String(50), nullable=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    forward_status = Column(String(20), default="pending")  # pending, success, failed, skipped
    forward_attempts = Column(Integer, default=0)
    forward_status_code = Column(Integer, nullable=True)

    bucket = relationship("Bucket", back_populates="events")


# Pydantic Schemas
class BucketCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    target_url: str | None = None
    forward_url: str | None = None
    expires_in_hours: int | None = Field(default=None, ge=1)


class BucketResponse(BaseModel):
    id: str
    name: str
    forward_url: str | None = None
    expires_in_hours: int | None = None
    created_at: str

    model_config = {"from_attributes": True}


class EventResponse(BaseModel):
    id: str
    bucket_id: str
    method: str
    headers: dict[str, str]
    payload: str | None = None
    client_ip: str | None = None
    timestamp: str
    forward_status: str
    forward_attempts: int
    forward_status_code: int | None = None

    model_config = {"from_attributes": True}


class StatsResponse(BaseModel):
    total_buckets: int
    total_events: int
    forwarded_success: int
    forwarded_failed: int
    success_rate_percent: float


async def forward_webhook_task(event_id: str, forward_url: str, method: str, headers: dict, payload: str | None):
    """Background task zur Weiterleitung mit Retry."""
    max_retries = 3
    timeout = httpx.Timeout(10.0, connect=5.0)

    # Bereinige Header für Forwarding
    forward_headers = {k: v for k, v in headers.items() if k.lower() not in {"host", "content-length"}}

    async with httpx.AsyncClient(timeout=timeout) as client:
        last_status_code = None
        forward_success = False

        for attempt in range(1, max_retries + 1):
            try:
                response = await client.request(
                    method=method,
                    url=forward_url,
                    headers=forward_headers,
                    content=payload.encode("utf-8") if payload is not None else None,
                )
                last_status_code = response.status_code
                if 200 <= response.status_code < 400:
                    forward_success = True
                    break
            except Exception as e:
                logger.warning(f"Versuch {attempt} Weiterleitung an {forward_url} fehlgeschlagen: {e}")
                if attempt < max_retries:
                    await asyncio.sleep(1.0 * attempt)

        # Status in DB aktualisieren
        async with async_session() as session:
            stmt = select(Event).where(Event.id == event_id)
            result = await session.execute(stmt)
            event = result.scalar_one_or_none()
            if event:
                event.forward_attempts = attempt
                event.forward_status_code = last_status_code
                event.forward_status = "success" if forward_success else "failed"
                await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Tabellen initialisieren
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(
    title="EventForge",
    description="Webhook Testing and Relay Gateway",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS-Konfiguration: allow_credentials darf nicht True sein bei allow_origins=["*"]
cors_origins_env = os.getenv("CORS_ORIGINS", "")
if cors_origins_env:
    allowed_origins = [origin.strip() for origin in cors_origins_env.split(",") if origin.strip()]
    allow_credentials = True
else:
    allowed_origins = ["*"]
    allow_credentials = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {"status": "ok", "app": "EventForge", "time": datetime.now(timezone.utc).isoformat()}


@app.post("/api/buckets", response_model=BucketResponse, status_code=status.HTTP_201_CREATED)
async def create_bucket(bucket_in: BucketCreate):
    # Unterstütze target_url als Alias für forward_url
    target = bucket_in.forward_url or bucket_in.target_url
    bucket_id = str(uuid.uuid4())
    bucket = Bucket(
        id=bucket_id,
        name=bucket_in.name,
        forward_url=target,
        expires_in_hours=bucket_in.expires_in_hours,
    )
    async with async_session() as session:
        session.add(bucket)
        await session.commit()
        await session.refresh(bucket)

    return BucketResponse(
        id=bucket.id,
        name=bucket.name,
        forward_url=bucket.forward_url,
        expires_in_hours=bucket.expires_in_hours,
        created_at=bucket.created_at.isoformat(),
    )


@app.get("/api/buckets", response_model=list[BucketResponse])
async def list_buckets():
    async with async_session() as session:
        stmt = select(Bucket).order_by(Bucket.created_at.desc())
        result = await session.execute(stmt)
        buckets = result.scalars().all()

    return [
        BucketResponse(
            id=b.id,
            name=b.name,
            forward_url=b.forward_url,
            expires_in_hours=b.expires_in_hours,
            created_at=b.created_at.isoformat(),
        )
        for b in buckets
    ]


@app.delete("/api/buckets/{bucket_id}", status_code=status.HTTP_200_OK)
async def delete_bucket(bucket_id: str):
    async with async_session() as session:
        stmt = select(Bucket).where(Bucket.id == bucket_id)
        result = await session.execute(stmt)
        bucket = result.scalar_one_or_none()
        if not bucket:
            raise HTTPException(status_code=404, detail="Bucket not found")

        await session.delete(bucket)
        await session.commit()

    return {"status": "success", "message": f"Bucket {bucket_id} gelöscht"}


@app.get("/api/buckets/{bucket_id}/events", response_model=list[EventResponse])
async def get_bucket_events(bucket_id: str):
    async with async_session() as session:
        # Prüfen ob Bucket existiert
        b_stmt = select(Bucket).where(Bucket.id == bucket_id)
        b_res = await session.execute(b_stmt)
        bucket = b_res.scalar_one_or_none()
        if not bucket:
            raise HTTPException(status_code=404, detail="Bucket not found")

        stmt = select(Event).where(Event.bucket_id == bucket_id).order_by(Event.timestamp.desc())
        result = await session.execute(stmt)
        events = result.scalars().all()

    resp = []
    for e in events:
        try:
            hdrs = json.loads(e.headers)
        except Exception:
            hdrs = {}
        resp.append(
            EventResponse(
                id=e.id,
                bucket_id=e.bucket_id,
                method=e.method,
                headers=hdrs,
                payload=e.payload,
                client_ip=e.client_ip,
                timestamp=e.timestamp.isoformat(),
                forward_status=e.forward_status,
                forward_attempts=e.forward_attempts,
                forward_status_code=e.forward_status_code,
            )
        )
    return resp


@app.get("/api/stats", response_model=StatsResponse)
async def get_stats():
    async with async_session() as session:
        bucket_count_stmt = select(func.count(Bucket.id))
        total_buckets = (await session.execute(bucket_count_stmt)).scalar() or 0

        event_count_stmt = select(func.count(Event.id))
        total_events = (await session.execute(event_count_stmt)).scalar() or 0

        success_stmt = select(func.count(Event.id)).where(Event.forward_status == "success")
        success_count = (await session.execute(success_stmt)).scalar() or 0

        failed_stmt = select(func.count(Event.id)).where(Event.forward_status == "failed")
        failed_count = (await session.execute(failed_stmt)).scalar() or 0

    total_forwarded = success_count + failed_count
    rate = round((success_count / total_forwarded * 100.0), 1) if total_forwarded > 0 else 100.0

    return StatsResponse(
        total_buckets=total_buckets,
        total_events=total_events,
        forwarded_success=success_count,
        forwarded_failed=failed_count,
        success_rate_percent=rate,
    )


# Webhook Ingestion Handler für /hook/{bucket_id} und /ingest/{bucket_id}
async def handle_ingest(bucket_id: str, request: Request, background_tasks: BackgroundTasks):
    async with async_session() as session:
        stmt = select(Bucket).where(Bucket.id == bucket_id)
        res = await session.execute(stmt)
        bucket = res.scalar_one_or_none()
        if not bucket:
            raise HTTPException(status_code=404, detail="Bucket not found")

        # Payload auslesen (JSON, Text, XML, etc.)
        raw_body = await request.body()
        payload_str = raw_body.decode("utf-8", errors="replace")

        headers_dict = dict(request.headers)
        client_ip = request.client.host if request.client else None

        forward_status_val = "pending" if bucket.forward_url else "skipped"

        event = Event(
            id=str(uuid.uuid4()),
            bucket_id=bucket.id,
            method=request.method,
            headers=json.dumps(headers_dict),
            payload=payload_str,
            client_ip=client_ip,
            forward_status=forward_status_val,
            forward_attempts=0,
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)

        # Asynchrone Weiterleitung triggern
        if bucket.forward_url:
            background_tasks.add_task(
                forward_webhook_task,
                event_id=event.id,
                forward_url=bucket.forward_url,
                method=request.method,
                headers=headers_dict,
                payload=payload_str,
            )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "received", "event_id": event.id, "bucket_id": bucket_id},
    )


# Beide Ingestion Pfade unterstützen (/hook/{bucket_id} und /ingest/{bucket_id})
@app.api_route("/hook/{bucket_id}", methods=["POST", "PUT", "PATCH"])
async def ingest_hook(bucket_id: str, request: Request, background_tasks: BackgroundTasks):
    return await handle_ingest(bucket_id, request, background_tasks)


@app.api_route("/ingest/{bucket_id}", methods=["POST", "PUT", "PATCH"])
async def ingest_webhook(bucket_id: str, request: Request, background_tasks: BackgroundTasks):
    return await handle_ingest(bucket_id, request, background_tasks)


# Statische Dateien einbinden (Dashboard unter /)
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
    app.mount("/", StaticFiles(directory="static", html=True), name="frontend")
