from datetime import datetime

from app.database import Base
from sqlalchemy import Column, DateTime, Float, Integer, String


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    status = Column(String(50), nullable=False, default="open")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class EndpointStatus(Base):
    __tablename__ = "endpoint_status"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, nullable=False, index=True)
    status_code = Column(Integer, nullable=False)
    response_time = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
