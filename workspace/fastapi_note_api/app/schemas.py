# app/schemas.py
from datetime import datetime

from pydantic import BaseModel, Field

class NoteBase(BaseModel):
    """Gemeinsame Felder für Note‑Schemas."""
    content: str = Field(..., min_length=1, description="Inhalt der Notiz")

class NoteCreate(NoteBase):
    """Schema für das Anlegen einer neuen Notiz."""
    pass

class NoteRead(NoteBase):
    """Schema für die Rückgabe einer Notiz."""
    id: int
    created_at: datetime

    class Config:
        orm_mode = True
