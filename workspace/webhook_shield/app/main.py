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
    payload = await request.json()
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

@app.get("/logs")
async def get_logs(db: Session = Depends(get_db)):
    return db.query(DeliveryLog).all()
