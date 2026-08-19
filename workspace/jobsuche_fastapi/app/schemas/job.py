# app/schemas/job.py
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel

class JobCreate(BaseModel):
    title: str
    description: str
    location: Optional[str] = None
    company: str
    industry: Optional[str] = None
    experience_level: Optional[str] = None
    contract_type: Optional[str] = None

class JobRead(BaseModel):
    id: int
    title: str
    description: str
    location: Optional[str] = None
    company: str
    industry: Optional[str] = None
    experience_level: Optional[str] = None
    contract_type: Optional[str] = None
    posted_at: datetime

    class Config:
        orm_mode = True

class JobFilter(BaseModel):
    query: Optional[str] = None          # Volltextsuche
    location: Optional[str] = None
    industry: Optional[str] = None
    experience_level: Optional[str] = None
    contract_type: Optional[str] = None
    skip: int = 0
    limit: int = 20
