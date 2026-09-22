"""Job-Modelle und Schemas für AetherMesh."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field

# Re-Exportiere ORM-Klasse und Enum aus db.models für Vertragskompatibilität
from app.db.models import Job, JobStatus


class JobCreate(BaseModel):
    """Schema zur Erstellung eines neuen Verarbeitungs-Jobs."""

    priority: int = Field(default=5, ge=1, le=10, description="Priorität von 1 (niedrig) bis 10 (hoch)")
    payload: Any = Field(default_factory=dict, description="Nutzdaten des Jobs")
    max_retries: int = Field(default=3, ge=0, le=10, description="Maximale Anzahl an Wiederholungsversuchen")


__all__ = ["Job", "JobStatus", "JobCreate"]
