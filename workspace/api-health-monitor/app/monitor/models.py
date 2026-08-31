from sqlalchemy import Column, Integer, String, Float, DateTime
from datetime import datetime
from app.db.database import Base

class UptimeRecord(Base):
    __tablename__ = "uptime_records"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    url = Column(String, index=True)
    status = Column(Integer)
    response_time = Column(Float)
    error_msg = Column(String, nullable=True)
