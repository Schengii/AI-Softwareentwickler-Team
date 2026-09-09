import enum
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AgentStatus(str, enum.Enum):
    ACTIVE = "active"
    IDLE = "idle"
    ERROR = "error"

class AgentLog(Base):
    __tablename__ = "agent_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    agent_name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    status: Mapped[AgentStatus] = mapped_column(Enum(AgentStatus), index=True, nullable=False)
    last_heartbeat: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now(), 
        onupdate=func.now(),
        index=True
    )
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", 
        JSON, 
        nullable=True, 
        default=None
    )

    def __repr__(self) -> str:
        return f"<AgentLog(agent_name='{self.agent_name}', status='{self.status}')>"
