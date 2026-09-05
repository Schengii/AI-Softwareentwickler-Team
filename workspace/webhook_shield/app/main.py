import json

from fastapi import Depends, FastAPI, HTTPException, Request
from sqlalchemy.orm import Session

from app.models import DeliveryLog, SessionLocal, Webhook, init_db

app = FastAPI(title="WebhookShield API")

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.on_event("startup")
async def startup_event():
    init_db()

@app.post("/webhooks/{endpoint_path}")
async def receive_webhook(
    endpoint_path: str,
    request: Request,
    db: Session = Depends(get_db)
):
    # 1. Check if webhook exists
    webhook = db.query(Webhook).filter(Webhook.endpoint_path == endpoint_path).first()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")

    # 2. Get payload and headers
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        # Ungültiges oder leeres JSON → 400 statt 500 (kein Traceback-Leak)
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    headers = dict(request.headers)

    # 3. Persist log
    log = DeliveryLog(
        webhook_id=webhook.id,
        payload_json=payload,
        headers_json=headers,
        status="received"
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    return {"status": "accepted", "log_id": log.id}

@app.get("/api/webhooks")
async def list_webhooks(db: Session = Depends(get_db)):
    """Liefert alle registrierten Webhooks – Endpunkt für das Dashboard."""
    return db.query(Webhook).all()

@app.get("/logs")
async def get_logs(db: Session = Depends(get_db)):
    return db.query(DeliveryLog).all()
