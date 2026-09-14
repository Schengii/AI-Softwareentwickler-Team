import uuid

from sqlalchemy import JSON, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True, default=None, index=True)
    action: Mapped[str] = mapped_column(String, nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    target_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    changes: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    tenant = relationship("Tenant", back_populates="audit_logs")
