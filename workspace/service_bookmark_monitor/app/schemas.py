"""Pydantic-Schemas (Request-/Response-Modelle) für Services und Bookmarks."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ServiceBase(BaseModel):
    """Gemeinsame Felder für Create- und Read-Schema eines Service."""

    name: str = Field(..., min_length=1, max_length=255)
    url: str = Field(..., min_length=1, max_length=2048)


class ServiceCreate(ServiceBase):
    """Payload für POST /services."""


class ServiceRead(ServiceBase):
    """Antwortmodell für einen Service inkl. DB-Attributen."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    last_checked: datetime | None = None


class BookmarkBase(BaseModel):
    """Gemeinsame Felder für Create- und Read-Schema von Bookmark."""

    title: str = Field(..., min_length=1, max_length=255)
    url: str = Field(..., min_length=1, max_length=2048)


class BookmarkCreate(BookmarkBase):
    """Payload für diesen Bookmark."""



class BookmarkRead(BookmarkBase):
    """Antwort vom Server für einen Bookmark inkl. DB-Attributen."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    last_checked: datetime | None = None