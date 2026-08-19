# app/models/job.py
from typing import Optional, List
from datetime import datetime
from sqlmodel import Field, SQLModel, Relationship

class JobBase(SQLModel):
    title: str
    description: str
    location: Optional[str] = None
    company: str
    industry: Optional[str] = None
    experience_level: Optional[str] = None   # Junior / Mid / Senior
    contract_type: Optional[str] = None      # Vollzeit, Teilzeit, Praktikum …
    posted_at: datetime = Field(default_factory=datetime.utcnow)

class Job(JobBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    applications: List["Application"] = Relationship(back_populates="job")
    saved_by: List["User"] = Relationship(back_populates="saved_jobs", link_model="SavedJobLink")
