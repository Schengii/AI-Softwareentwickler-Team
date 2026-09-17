from datetime import datetime

from pydantic import BaseModel


class DocumentBase(BaseModel):
    filename: str
    content: str

class DocumentCreate(DocumentBase):
    pass

class DocumentOut(BaseModel):
    id: int
    filename: str
    status: str
    quarantine_reason: str | None = None
    reviewer_notes: str | None = None
    created_at: datetime
    released_at: datetime | None = None

    model_config = {"from_attributes": True}

class DocumentRelease(BaseModel):
    reviewer_notes: str | None = None
