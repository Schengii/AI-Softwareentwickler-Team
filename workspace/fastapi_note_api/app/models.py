from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field, Column, Text


class Note(SQLModel, table=True):
    """Datenbankmodell für eine Notiz."""
    id: Optional[int] = Field(default=None, primary_key=True)
    content: str = Field(sa_column=Column(Text), nullable=False)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
