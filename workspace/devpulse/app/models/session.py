from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"), index=True)
    start_time: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    note: Mapped[str | None] = mapped_column(String, nullable=True, default=None)

    project = relationship("Project", back_populates="sessions")
