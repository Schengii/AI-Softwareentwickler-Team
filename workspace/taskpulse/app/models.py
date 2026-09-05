# <!-- BEGIN FILE: app/models.py -->
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(50), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

class EndpointStatus(Base):
    __tablename__ = "endpoint_status"
    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(255))
    status_code: Mapped[int] = mapped_column()
    response_time: Mapped[float] = mapped_column()
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=func.now())
# <!-- END FILE: app/models.py -->
