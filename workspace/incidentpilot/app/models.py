from datetime import datetime, timedelta

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    delete,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    role = Column(String, default="user")

class Check(Base):
    __tablename__ = "checks"
    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, nullable=False)
    interval_seconds = Column(Integer, default=60)
    created_at = Column(DateTime, server_default=func.now())
    owner_id = Column(Integer, ForeignKey("users.id"))

class AlertConfig(Base):
    __tablename__ = "alert_configs"
    id = Column(Integer, primary_key=True, index=True)
    type = Column(String)
    target = Column(String)
    enabled = Column(Boolean, default=True)
    check_id = Column(Integer, ForeignKey("checks.id"))

class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String, index=True)
    payload = Column(JSON)
    received_at = Column(DateTime, server_default=func.now(), index=True)

async def save_incident(db: AsyncSession, event_type: str, payload: dict):
    # PII-Filter
    pii_fields = {"email", "password", "token", "api_key"}
    filtered_payload = {k: v for k, v in payload.items() if k not in pii_fields}
    
    new_event = WebhookEvent(
        event_type=event_type,
        payload=filtered_payload
    )
    db.add(new_event)
    await db.commit()

async def cleanup_old_events(db: AsyncSession):
    threshold = datetime.utcnow() - timedelta(days=30)
    await db.execute(delete(WebhookEvent).where(WebhookEvent.received_at < threshold))
    await db.commit()
