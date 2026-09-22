from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.sql import func

from app.db.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    action = Column(String, nullable=False)
    secret_name = Column(String, nullable=False)
    actor_ip = Column(String, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    status = Column(String, nullable=False)

class AuditLogResponse(BaseModel):
    id: int
    action: str
    secret_name: str
    actor_ip: str | None = None
    timestamp: datetime
    status: str

    model_config = {"from_attributes": True}
