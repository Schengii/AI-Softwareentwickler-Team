import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class Saga(Base):
    __tablename__ = "sagas"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workflow_type = Column(String, nullable=False)
    status = Column(String, nullable=False, default="PENDING")
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    steps = relationship("SagaStep", back_populates="saga", cascade="all, delete-orphan")

class SagaStep(Base):
    __tablename__ = "saga_steps"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    saga_id = Column(String, ForeignKey("sagas.id"), nullable=False)
    step_name = Column(String, nullable=False)
    status = Column(String, nullable=False)
    result = Column(JSON, nullable=True)
    error = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    saga = relationship("Saga", back_populates="steps")

class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    key = Column(String, primary_key=True)
    response_body = Column(JSON, nullable=False)
    status_code = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
