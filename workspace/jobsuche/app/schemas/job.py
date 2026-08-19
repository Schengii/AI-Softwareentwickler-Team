# app/schemas/job.py
from __future__ import annotations
from pydantic import BaseModel, Field, validator
from typing import Optional
from datetime import datetime

class JobBase(BaseModel):
    title: str = Field(..., max_length=150)
    company: str = Field(..., max_length=100)
    location: str = Field(..., max_length=100)
    salary: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = Field(None, max_length=5000)

    @validator("*")
    def strip_whitespace(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

class JobCreate(JobBase):
    pass

class JobRead(JobBase):
    id: str
    posted_at: datetime
    is_active: bool

    class Config:
        orm_mode = True
