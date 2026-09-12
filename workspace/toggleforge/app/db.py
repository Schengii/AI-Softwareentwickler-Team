"""Datenbank-Modelle, Engine und Session-Management für ToggleForge."""

from collections.abc import AsyncGenerator
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base, relationship

DATABASE_URL = "sqlite+aiosqlite:///./toggleforge.db"

engine = create_async_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

async_session = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

Base = declarative_base()


class FeatureFlag(Base):
    """Datenbank-Modell für Feature-Flags."""

    __tablename__ = "feature_flags"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    key = Column(String(100), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    flag_type = Column(String(50), nullable=False, default="boolean")
    enabled = Column(Boolean, nullable=False, default=False)
    rollout_percentage = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    targeting_rules = relationship(
        "TargetingRule",
        back_populates="feature_flag",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class TargetingRule(Base):
    """Datenbank-Modell für Targeting-Regeln eines Feature-Flags."""

    __tablename__ = "targeting_rules"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    flag_id = Column(Integer, ForeignKey("feature_flags.id", ondelete="CASCADE"), nullable=False)
    attribute_name = Column(String(100), nullable=False)
    operator = Column(String(50), nullable=False)
    values = Column(JSON, nullable=False, default=list)
    enabled = Column(Boolean, nullable=False, default=True)
    priority = Column(Integer, nullable=False, default=0)

    feature_flag = relationship("FeatureFlag", back_populates="targeting_rules")


class AuditLog(Base):
    """Datenbank-Modell für Audit-Logs von Flag-Änderungen."""

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    flag_key = Column(String(100), index=True, nullable=False)
    action = Column(String(50), nullable=False)
    actor = Column(String(100), nullable=True, default="system")
    old_state = Column(Text, nullable=True)
    new_state = Column(Text, nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI-Dependency für asynchrone Datenbank-Sessions."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Initialisiert die Datenbanktabellen beim Anwendungsstart."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Schließt die Datenbankverbindung beim Herunterfahren."""
    await engine.dispose()
