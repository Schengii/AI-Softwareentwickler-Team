import datetime

from sqlalchemy import Column, DateTime, Index, Integer, String, Text

from app.database import Base


class LogEntry(Base):
    __tablename__ = "log_entries"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    level = Column(String, index=True)
    source = Column(String)
    message = Column(Text)

Index("ix_log_level_timestamp", LogEntry.level, LogEntry.timestamp)
