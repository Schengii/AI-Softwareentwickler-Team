import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SecretStatus(str, enum.Enum):
    active = "active"
    revoked = "revoked"
    expired = "expired"

class Secret(Base):
    __tablename__ = "secrets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    encrypted_value: Mapped[str] = mapped_column(String, nullable=False)
    ttl_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    status: Mapped[SecretStatus] = mapped_column(Enum(SecretStatus), default=SecretStatus.active, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None, index=True)
