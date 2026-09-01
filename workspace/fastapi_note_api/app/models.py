from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field, Column, Text


class Note(SQLModel, table=True):
    """Datenbankmodell für eine Notiz."""
    id: Optional[int] = Field(default=None, primary_key=True)
    # SQLModel erlaubt "nullable" NICHT zusammen mit einem eigenen "sa_column" - die
    # Nullability muss dann direkt auf der Column gesetzt werden (sonst RuntimeError beim
    # Import: "Passing nullable is not supported when also passing a sa_column").
    content: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
