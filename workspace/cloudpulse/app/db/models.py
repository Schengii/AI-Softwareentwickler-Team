from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String

from app.db.base import Base


class Monitor(Base):
    __tablename__ = "monitors"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)
    url = Column(String, nullable=False)
    interval_seconds = Column(Integer, default=60, nullable=False)
    expected_status = Column(Integer, default=200, nullable=False)
    timeout = Column(Integer, default=5, nullable=False)
    
    last_checked = Column(DateTime, nullable=True)
    last_status_code = Column(Integer, nullable=True)
    last_latency_ms = Column(Float, nullable=True)
    is_up = Column(Boolean, nullable=True)
    last_error = Column(String, nullable=True)
