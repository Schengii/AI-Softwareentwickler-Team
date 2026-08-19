# app/models/application.py
from typing import Optional
from datetime import datetime
from sqlmodel import Field, SQLModel, Relationship

class ApplicationBase(SQLModel):
    cover_letter: Optional[str] = None
    status: str = Field(default="submitted")   # submitted, reviewed, rejected, accepted
    applied_at: datetime = Field(default_factory=datetime.utcnow)

class Application(ApplicationBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    applicant_id: int = Field(foreign_key="user.id")
    job_id: int = Field(foreign_key="job.id")
    cv_path: Optional[str] = None

    applicant: "User" = Relationship(back_populates="applications")
    job: "Job" = Relationship(back_populates="applications")
