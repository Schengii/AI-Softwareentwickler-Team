# ✅ SQLAlchemy Model-Definition mit Unique Constraint
from sqlalchemy import Column, String, UniqueConstraint

from app.db.session import Base


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    
    id = Column(String(64), primary_key=True, index=True)
    source_slug = Column(String(64), nullable=False, index=True)
    idempotency_key = Column(String(128), nullable=True, index=True)
    payload_hash = Column(String(64), nullable=False)
    status = Column(String(32), default="PENDING", nullable=False)
    
    __table_args__ = (
        UniqueConstraint("source_slug", "idempotency_key", name="uq_source_idempotency"),
    )
