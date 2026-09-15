from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class LogEntry(Base):
    __tablename__ = "log_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False
    )
    level: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    service_name: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    payload: Mapped[str | None] = mapped_column(String, nullable=True, default=None)

    __table_args__ = (
        Index("ix_log_entries_service_level", "service_name", "level"),
    )
