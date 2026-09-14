import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class FeatureFlag(Base):
    __tablename__ = "feature_flags"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), index=True, nullable=False)
    key: Mapped[str] = mapped_column(String, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    rules: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    tenant = relationship("Tenant", back_populates="flags")

    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uix_tenant_flag_key"),
    )
