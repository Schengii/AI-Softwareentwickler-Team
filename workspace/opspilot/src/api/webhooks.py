import hashlib
import hmac

from app.models import Incident
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Base, engine, get_db

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# In Produktion aus Umgebungsvariable laden
WEBHOOK_SECRET = b"super-secret-key"

async def verify_signature(
    request: Request,
    x_opspilot_signature: str = Header(..., alias="X-OpsPilot-Signature")
):
    payload = await request.body()
    expected_signature = hmac.new(
        WEBHOOK_SECRET,
        msg=payload,
        digestmod=hashlib.sha256
    ).hexdigest()
    
    if not hmac.compare_digest(expected_signature, x_opspilot_signature):
        raise HTTPException(status_code=401, detail="Invalid signature")
    return True

@router.post("/ingest", status_code=202, dependencies=[Depends(verify_signature)])
async def ingest_webhook(payload: dict, db: AsyncSession = Depends(get_db)):
    """
    Nimmt externe Webhooks entgegen, validiert die Signatur und persistiert den Vorfall
    als neuen Incident-Datensatz. Die eigentliche Workflow-Ausfuehrung (Zuordnung zu
    Runbooks, Benachrichtigung, ...) laeuft asynchron auf Basis dieses Datensatzes und
    ist nicht Teil dieses schnellen Ingest-Endpunkts.
    """
    # In Produktion legt Alembic (siehe docs/adr/0005) das Schema vorab an; fuer den
    # aktuellen Stand ohne Migrationstooling stellt create_all() idempotent sicher, dass
    # die Tabelle existiert, bevor der erste Datensatz geschrieben wird.
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    title = str(payload.get("title") or payload.get("message") or "Webhook-Incident ohne Titel")
    incident = Incident(title=title, status="open", payload=payload)
    db.add(incident)
    await db.commit()
    await db.refresh(incident)
    return {"status": "accepted", "incident_id": incident.id}
