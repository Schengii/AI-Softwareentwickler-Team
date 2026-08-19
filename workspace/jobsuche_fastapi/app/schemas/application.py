# app/schemas/application.py
from typing import Optional
from pydantic import BaseModel

class ApplicationCreate(BaseModel):
    job_id: int
    cover_letter: Optional[str] = None

class ApplicationRead(BaseModel):
    id: int
    job_id: int
    applicant_id: int
    status: str
    applied_at: str
    cv_path: Optional[str] = None

    class Config:
        orm_mode = True
