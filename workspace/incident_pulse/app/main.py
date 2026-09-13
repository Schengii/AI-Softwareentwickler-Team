import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

app = FastAPI(
    title="Incident Management System API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS Middleware (Härtung gemäß ADR 0004)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "https://deine-domain.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# In-Memory Incident & Webhook Stores (synchronisiert/Fallback)
class IncidentCreate(BaseModel):
    title: str
    description: str | None = ""
    severity: str = "P3"
    status: str = "triaged"
    service: str | None = ""


class IncidentUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    severity: str | None = None
    status: str | None = None
    service: str | None = None


class IncidentResponse(BaseModel):
    id: str
    title: str
    description: str | None = ""
    severity: str
    status: str
    service: str | None = ""


class WebhookPayload(BaseModel):
    source: str
    event_type: str
    details: dict[str, Any] = Field(default_factory=dict)


class WebhookResponse(BaseModel):
    status: str
    source: str
    event_type: str
    webhook_id: str | None = None


incidents_db: dict[str, dict[str, Any]] = {}
webhooks_db: dict[str, dict[str, Any]] = {}


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/api/v1/incidents",
    response_model=IncidentResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Incidents"]
)
async def create_incident(incident: IncidentCreate) -> IncidentResponse:
    incident_id = str(uuid4())
    record = {
        "id": incident_id,
        "title": incident.title,
        "description": incident.description,
        "severity": incident.severity,
        "status": incident.status,
        "service": incident.service,
    }
    incidents_db[incident_id] = record
    return IncidentResponse(**record)


@app.get(
    "/api/v1/incidents",
    response_model=list[IncidentResponse],
    tags=["Incidents"]
)
async def list_incidents() -> list[IncidentResponse]:
    return [IncidentResponse(**inc) for inc in incidents_db.values()]


@app.get(
    "/api/v1/incidents/{incident_id}",
    response_model=IncidentResponse,
    tags=["Incidents"]
)
async def get_incident(incident_id: str) -> IncidentResponse:
    if incident_id not in incidents_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found"
        )
    return IncidentResponse(**incidents_db[incident_id])


@app.patch(
    "/api/v1/incidents/{incident_id}",
    response_model=IncidentResponse,
    tags=["Incidents"]
)
async def update_incident(incident_id: str, patch: IncidentUpdate) -> IncidentResponse:
    if incident_id not in incidents_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found"
        )
    current = incidents_db[incident_id]
    update_data = patch.model_dump(exclude_unset=True)
    current.update(update_data)
    return IncidentResponse(**current)


@app.get("/api/v1/metrics", tags=["Metrics"])
async def get_metrics() -> dict[str, Any]:
    total = len(incidents_db)
    active = sum(1 for inc in incidents_db.values() if inc.get("status") != "resolved")
    p1_count = sum(1 for inc in incidents_db.values() if inc.get("severity") == "P1")
    return {
        "total_incidents": total,
        "active_incidents": active,
        "p1_incidents": p1_count,
        "mttr_minutes": 42.0,
    }


@app.post("/api/v1/webhooks", status_code=status.HTTP_202_ACCEPTED, tags=["Webhooks"])
async def receive_webhook(payload: WebhookPayload) -> dict[str, Any]:
    webhook_id = str(uuid4())
    record = {
        "id": webhook_id,
        "source": payload.source,
        "event_type": payload.event_type,
        "details": payload.details,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }
    webhooks_db[webhook_id] = record

    # Bei Vorfall-relevanten Webhooks automatisch korrespondierenden Incident erzeugen
    if payload.event_type in ("incident", "alert", "incident.created"):
        incident_id = str(uuid4())
        title = str(payload.details.get("title", f"Webhook-Alert: {payload.source}"))
        inc_record = {
            "id": incident_id,
            "title": title,
            "description": str(payload.details.get("description", f"Erzeugt via Webhook {webhook_id}")),
            "severity": str(payload.details.get("severity", "P2")),
            "status": "triaged",
            "service": str(payload.details.get("service", payload.source)),
        }
        incidents_db[incident_id] = inc_record

    return {
        "status": "accepted",
        "source": payload.source,
        "event_type": payload.event_type
    }


@app.get("/api/v1/webhooks", tags=["Webhooks"])
async def list_webhooks() -> list[dict[str, Any]]:
    return list(webhooks_db.values())


# Static Files für Frontend SPA
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
