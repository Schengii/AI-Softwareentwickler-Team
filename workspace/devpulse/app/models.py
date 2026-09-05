from sqlalchemy import Column, DateTime, Integer, String, func

from app.core.database import Base


class Service(Base):
    __tablename__ = "services"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    status = Column(String)  # e.g., "UP", "DOWN"
    last_checked = Column(DateTime, default=func.now(), onupdate=func.now())

class Incident(Base):
    __tablename__ = "incidents"
    id = Column(Integer, primary_key=True, index=True)
    service_id = Column(Integer, index=True)
    title = Column(String)
    description = Column(String)
    created_at = Column(DateTime, default=func.now())
