"""
Jobs‑Search‑Service – Clean‑Architecture, Type‑Safety, SOLID.
"""

from __future__ import annotations

from typing import Protocol, TypedDict, List, Optional
from dataclasses import dataclass

from pydantic import BaseModel, Field, validator
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import Session

# ----------------------------------------------------------------------
# 1️⃣ Domain‑Model (Value Objects) – stark typisiert
# ----------------------------------------------------------------------
class SalaryRange(BaseModel):
    """Immutable Value Object für Gehaltsbereich."""
    min: Optional[int] = Field(None, ge=0)
    max: Optional[int] = Field(None, ge=0)

    @validator("max")
    def max_must_be_ge_min(cls, v, values):
        if v is not None and values.get("min") is not None and v < values["min"]:
            raise ValueError("max must be >= min")
        return v


class JobFilter(BaseModel):
    query: str = ""
    location: Optional[str] = None
    salary: SalaryRange = SalaryRange()
    page: int = Field(1, ge=1)
    size: int = Field(20, ge=1, le=100)


class JobDTO(BaseModel):
    """Data‑Transfer‑Object – einzige Quelle der Wahrheit für UI."""
    id: int
    title: str
    company: str
    location: str
    salary: Optional[int] = None
    posted_at: str  # ISO‑String, UI‑seitig formatierbar


# ----------------------------------------------------------------------
# 2️⃣ Repository‑Abstraktion (Dependency Inversion)
# ----------------------------------------------------------------------
class JobRepository(Protocol):
    def search(self, filter: JobFilter) -> List[JobDTO]: ...


# ----------------------------------------------------------------------
# 3️⃣ Konkrete SQL‑Alchemy‑Implementierung
# ----------------------------------------------------------------------
@dataclass
class SqlAlchemyJobRepository:
    session: Session

    def search(self, filter: JobFilter) -> List[JobDTO]:
        stmt = select(
            Job.id,
            Job.title,
            Job.company,
            Job.location,
            Job.salary,
            Job.posted_at,
        ).where(
            and_(
                Job.title.ilike(f"%{filter.query}%"),
                *(Job.location == filter.location if filter.location else []),
                *(Job.salary >= filter.salary.min if filter.salary.min else []),
                *(Job.salary <= filter.salary.max if filter.salary.max else []),
            )
        ).order_by(Job.posted_at.desc()).limit(filter.size).offset(
            (filter.page - 1) * filter.size
        )
        rows = self.session.execute(stmt).all()
        return [JobDTO(**dict(row)) for row in rows]


# ----------------------------------------------------------------------
# 4️⃣ Use‑Case / Interactor (Single‑Responsibility)
# ----------------------------------------------------------------------
class SearchJobsUseCase:
    """Orchestriert das Suchen von Jobs – rein business‑logisch."""

    def __init__(self, repo: JobRepository) -> None:
        self._repo = repo

    def execute(self, raw_params: dict) -> List[JobDTO]:
        """
        1️⃣ Eingabe‑Validierung & Normalisierung (Pydantic)
        2️⃣ Delegation an Repository
        3️⃣ Rückgabe von DTOs (keine HTML‑Erzeugung)
        """
        filter_obj = JobFilter(**raw_params)  # ValidationError → 400 Bad Request
        return self._repo.search(filter_obj)
