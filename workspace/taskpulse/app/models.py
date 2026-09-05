from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String

from app.database import Base


class Task(Base):
    """Hintergrund-Aufgabe im Monitoring-Dashboard."""

    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class EndpointStatus(Base):
    """Gemessener Status eines überwachten API-Endpunkts."""

    __tablename__ = "endpoint_status"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String(500), nullable=False)
    status_code = Column(Integer, nullable=False)
    response_time = Column(Float, nullable=False)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
