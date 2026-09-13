"""HyperionSentinel Database & Storage Engine.

Enthält asynchrone SQLAlchemy 2.0 Modelle und Storage-Services für:
- API-Keys (kryptographisch gehasht mit Scopes, Rollen und Tiers)
- RBAC-Regeln (Rollen, Ressourcen, Berechtigungen)
- Audit-Logs (Security-Events, Rate-Limit-Verstöße, Anomalien)
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import StaticPool

# -----------------------------------------------------------------------------
# Database Configuration & Base
# -----------------------------------------------------------------------------
DATABASE_URL = os.getenv(
    "HYPERION_DATABASE_URL",
    "sqlite+aiosqlite:///./hyperion_sentinel.db",
)

engine_kwargs: dict[str, Any] = {"echo": False}
if "sqlite" in DATABASE_URL:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
    if ":memory:" in DATABASE_URL:
        engine_kwargs["poolclass"] = StaticPool

async_engine: AsyncEngine = create_async_engine(DATABASE_URL, **engine_kwargs)
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Zentrale Declarative Base für HyperionSentinel nach Single-DB-Paradigma."""


# -----------------------------------------------------------------------------
# SQLAlchemy Modelle
# -----------------------------------------------------------------------------
class APIKey(Base):
    """Speichert API-Keys kryptographisch sicher mit Scopes, Limits und Mandanten."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key_prefix: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    client_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False, default="default")
    name: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    role: Mapped[str] = mapped_column(String(64), index=True, nullable=False, default="viewer")
    scopes: Mapped[str] = mapped_column(Text, nullable=False, default="read")  # Kommagetrennte Scopes
    rate_limit_tier: Mapped[str] = mapped_column(String(64), nullable=False, default="standard")
    custom_rpm_limit: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, index=True, nullable=False, default=True)
    expires_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
    )
    last_used_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    __table_args__ = (
        Index("ix_api_keys_tenant_client", "tenant_id", "client_id"),
    )

    @classmethod
    def hash_key(cls, raw_key: str) -> str:
        """Erzeugt SHA-256 Hash des Roh-Schlüssels."""
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    def get_scopes_list(self) -> list[str]:
        return [s.strip() for s in self.scopes.split(",") if s.strip()]


class RBACRule(Base):
    """Speichert Zugriffskontrollregeln (Rollen, Pfade, HTTP-Methoden und Berechtigungen)."""

    __tablename__ = "rbac_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    resource_path: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    http_method: Mapped[str] = mapped_column(String(16), nullable=False, default="*")
    required_scope: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
    is_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True, default=None)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("role", "resource_path", "http_method", name="uq_rbac_role_resource_method"),
        Index("ix_rbac_lookup", "role", "resource_path"),
    )


class AuditLog(Base):
    """Manipulationssichere und performante Erfassung sicherheitsrelevanter Events."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    severity: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="INFO")
    client_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True, default=None)
    tenant_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True, default=None)
    ip_address: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True, default=None)
    endpoint: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True, default=None)
    http_method: Mapped[str | None] = mapped_column(String(16), nullable=True, default=None)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    details: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    timestamp: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
        nullable=False,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
    )

    __table_args__ = (
        Index("ix_audit_logs_event_ts", "event_type", "timestamp"),
        Index("ix_audit_logs_client_ts", "client_id", "timestamp"),
    )


# -----------------------------------------------------------------------------
# Dependency & Lifecycle
# -----------------------------------------------------------------------------
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Dependency zur Bereitstellung einer transaktionalen DB-Session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Initialisiert alle Tabellen asynchron (für Startup oder Lifespan)."""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# -----------------------------------------------------------------------------
# Storage Service Repository
# -----------------------------------------------------------------------------
class StorageEngine:
    """Service-Klasse für standardisierte DB-Operationen auf API-Keys, RBAC und Audits."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # API-Key Management
    async def create_api_key(
        self,
        raw_key: str,
        client_id: str,
        tenant_id: str = "default",
        name: str | None = None,
        role: str = "viewer",
        scopes: str = "read",
        rate_limit_tier: str = "standard",
        custom_rpm_limit: int | None = None,
        expires_at: datetime.datetime | None = None,
    ) -> APIKey:
        prefix = raw_key[:8] if len(raw_key) >= 8 else raw_key
        key_hash = APIKey.hash_key(raw_key)
        api_key = APIKey(
            key_prefix=prefix,
            key_hash=key_hash,
            client_id=client_id,
            tenant_id=tenant_id,
            name=name,
            role=role,
            scopes=scopes,
            rate_limit_tier=rate_limit_tier,
            custom_rpm_limit=custom_rpm_limit,
            expires_at=expires_at,
        )
        self.session.add(api_key)
        await self.session.flush()
        return api_key

    async def get_api_key_by_hash(self, key_hash: str) -> APIKey | None:
        stmt = select(APIKey).where(APIKey.key_hash == key_hash, APIKey.is_active == True)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def verify_and_touch_key(self, raw_key: str) -> APIKey | None:
        key_hash = APIKey.hash_key(raw_key)
        api_key = await self.get_api_key_by_hash(key_hash)
        if not api_key:
            return None
        if api_key.expires_at and api_key.expires_at < datetime.datetime.now(datetime.timezone.utc):
            return None
        api_key.last_used_at = datetime.datetime.now(datetime.timezone.utc)
        await self.session.flush()
        return api_key

    # RBAC Management
    async def add_rbac_rule(
        self,
        role: str,
        resource_path: str,
        http_method: str = "*",
        required_scope: str | None = None,
        is_allowed: bool = True,
        description: str | None = None,
    ) -> RBACRule:
        rule = RBACRule(
            role=role,
            resource_path=resource_path,
            http_method=http_method.upper(),
            required_scope=required_scope,
            is_allowed=is_allowed,
            description=description,
        )
        self.session.add(rule)
        await self.session.flush()
        return rule

    async def check_access(
        self,
        role: str,
        resource_path: str,
        http_method: str,
        provided_scopes: list[str] | None = None,
    ) -> bool:
        if role == "admin":
            return True
        stmt = select(RBACRule).where(
            RBACRule.role == role,
            RBACRule.resource_path == resource_path,
            RBACRule.http_method.in_(["*", http_method.upper()]),
        )
        res = await self.session.execute(stmt)
        rule = res.scalars().first()
        if not rule:
            return False
        if not rule.is_allowed:
            return False
        if rule.required_scope:
            if not provided_scopes or rule.required_scope not in provided_scopes:
                return False
        return True

    # Audit Logging
    async def log_event(
        self,
        event_type: str,
        severity: str = "INFO",
        client_id: str | None = None,
        tenant_id: str | None = None,
        ip_address: str | None = None,
        endpoint: str | None = None,
        http_method: str | None = None,
        status_code: int | None = None,
        details: dict | str | None = None,
    ) -> AuditLog:
        raw_details = json.dumps(details) if isinstance(details, dict) else details
        log_entry = AuditLog(
            event_type=event_type,
            severity=severity,
            client_id=client_id,
            tenant_id=tenant_id,
            ip_address=ip_address,
            endpoint=endpoint,
            http_method=http_method,
            status_code=status_code,
            details=raw_details,
        )
        self.session.add(log_entry)
        await self.session.flush()
        return log_entry

    async def get_recent_audit_logs(self, limit: int = 100) -> list[AuditLog]:
        stmt = select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())
