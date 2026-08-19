# db/models.py
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum as PyEnum
from typing import List, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Basis-Klasse für alle SQLAlchemy-Modelle"""
    pass


class ApplicationStatus(str, PyEnum):
    DRAFT = "DRAFT"
    APPLIED = "APPLIED"
    INTERVIEWING = "INTERVIEWING"
    OFFER_RECEIVED = "OFFER_RECEIVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    applications: Mapped[List["JobApplication"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    salary_entries: Mapped[List["SalaryAnalytics"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    reminders: Mapped[List["Reminder"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class JobApplication(Base):
    __tablename__ = "job_applications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    job_title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus), default=ApplicationStatus.DRAFT, nullable=False
    )
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    job_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description_raw: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="applications")
    salary_analytics: Mapped[Optional["SalaryAnalytics"]] = relationship(
        back_populates="job_application", uselist=False
    )


class SalaryAnalytics(Base):
    __tablename__ = "salary_analytics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_application_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("job_applications.id", ondelete="SET NULL"), nullable=True
    )

    # Präzise Gehaltsangaben (Fix für Float-Issue: Numeric(12, 2))
    base_salary_yearly: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    bonus_yearly: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    
    # Metadaten für Vergleiche
    location: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    experience_years: Mapped[int] = mapped_column(nullable=False)
    industry: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role_level: Mapped[str] = mapped_column(String(100), nullable=False) # z.B. Junior, Senior, Lead
    
    calculated_total_yearly: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="salary_entries")
    job_application: Mapped[Optional["JobApplication"]] = relationship(back_populates="salary_analytics")


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="reminders")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True) # z.B. APPLICATION_CREATED
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True) # Postgres JSONB für strukturierte Logs
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
